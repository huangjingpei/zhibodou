// update_tester.cpp — PDK 客户端升级链路测试程序（appId=4）
//
// 职责（对应正式客户端的 manager.py）：
//   1. 启动时若带 PDK_UPDATE_HEALTH_FILE/NONCE 环境变量 → 写健康握手文件（升级器健康检查依据）
//   2. 读取同目录 client-update.json（appId/version/serverBaseUrl/artifactPublicKeys）
//   3. GET /api/v1/client/updates/check 判断是否有更新
//   4. 断点续传下载构件到 %LOCALAPPDATA%\PDK\updates\cache\artifact-<id>.zip，校验 SHA-256
//   5. 生成 job.json（schemaVersion=1），把 pdk_updater.exe 复制到 cache 运行目录后拉起
//   6. 立即退出（升级器等父进程退出后做验签→原子替换/就地同步→健康检查→回滚）
//
// 构建（VS x64 环境）：
//   cl /nologo /std:c++17 /EHsc /O2 /W3 /utf-8 /Fe:update_tester.exe update_tester.cpp
//      winhttp.lib bcrypt.lib advapi32.lib
//
// 注意：真正的 Ed25519 验签 / manifest 校验 / 目录替换全部由 pdk_updater.exe 完成，
// 本程序只透传 check 响应里的 signature，并从 client-update.json 取受信公钥写入 job.json。

#include <windows.h>
#include <winhttp.h>
#include <bcrypt.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "bcrypt.lib")
#pragma comment(lib, "advapi32.lib")

namespace {

// ---------------------------------------------------------------- 工具

std::string wide_to_utf8(const std::wstring& w) {
    if (w.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), s.data(), n, nullptr, nullptr);
    return s;
}

std::wstring utf8_to_wide(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), w.data(), n);
    return w;
}

std::string getenv_str(const char* name) {
    char buf[1024] = {0};
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
    if (n == 0 || n >= sizeof(buf)) return {};
    return buf;
}

std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\r\n\"");
    if (a == std::string::npos) return {};
    size_t b = s.find_last_not_of(" \t\r\n\"");
    return s.substr(a, b - a + 1);
}

std::string json_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (unsigned char c : s) {
        switch (c) {
            case '\\': out += "\\\\"; break;
            case '"':  out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) { char b[8]; sprintf_s(b, "\\u%04x", c); out += b; }
                else out += (char)c;
        }
    }
    return out;
}

// 在 text 中查找 "key" 后面的 JSON 值区域。
//   find_string: 返回去引号的字符串值
//   find_number: 返回数字文本
//   find_object: 返回花括号匹配的完整对象子串（含花括号）
//   region 参数限定搜索范围（用于嵌套，如 artifact 对象内部）。
std::string::size_type find_key(const std::string& region, const std::string& key,
                                std::string::size_type from = 0) {
    std::string needle = "\"" + key + "\"";
    std::string::size_type pos = region.find(needle, from);
    while (pos != std::string::npos) {
        // 避免前缀误匹配（如 "artifactId" 匹配到 "artifactIdX"），needle 自带闭合引号已足够
        std::string::size_type colon = region.find(':', pos + needle.size());
        if (colon != std::string::npos && colon - pos < needle.size() + 8) return colon;
        pos = region.find(needle, pos + 1);
    }
    return std::string::npos;
}

bool find_string(const std::string& region, const std::string& key, std::string* out) {
    std::string::size_type colon = find_key(region, key);
    if (colon == std::string::npos) return false;
    std::string::size_type q1 = region.find('"', colon + 1);
    if (q1 == std::string::npos) return false;
    std::string value;
    for (std::string::size_type i = q1 + 1; i < region.size(); ++i) {
        char c = region[i];
        if (c == '\\' && i + 1 < region.size()) {
            char n = region[++i];
            switch (n) {
                case '"': case '\\': case '/': value += n; break;
                case 'n': value += '\n'; break;
                case 'r': value += '\r'; break;
                case 't': value += '\t'; break;
                case 'b': value += '\b'; break;
                case 'f': value += '\f'; break;
                case 'u': {
                    if (i + 4 >= region.size()) return false;
                    std::string hex = region.substr(i + 1, 4);
                    wchar_t wc = (wchar_t)strtoul(hex.c_str(), nullptr, 16);
                    i += 4;
                    // 简化：只处理 BMP，忽略代理对
                    char utf8[8];
                    int len = WideCharToMultiByte(CP_UTF8, 0, &wc, 1, utf8, sizeof(utf8), nullptr, nullptr);
                    if (len > 0) value.append(utf8, len);
                    break;
                }
                default: return false;
            }
        } else if (c == '"') {
            *out = value;
            return true;
        } else {
            value += c;
        }
    }
    return false;
}

bool find_number(const std::string& region, const std::string& key, long long* out) {
    std::string::size_type colon = find_key(region, key);
    if (colon == std::string::npos) return false;
    std::string::size_type i = colon + 1;
    while (i < region.size() && (region[i] == ' ' || region[i] == '\t')) ++i;
    char* end = nullptr;
    long long v = _strtoll_l(region.c_str() + i, &end, 10, nullptr);
    if (end == region.c_str() + i) return false;
    *out = v;
    return true;
}

bool find_object(const std::string& region, const std::string& key, std::string* out) {
    std::string::size_type colon = find_key(region, key);
    if (colon == std::string::npos) return false;
    std::string::size_type open = region.find('{', colon + 1);
    if (open == std::string::npos) return false;
    int depth = 0;
    bool in_str = false;
    for (std::string::size_type i = open; i < region.size(); ++i) {
        char c = region[i];
        if (in_str) {
            if (c == '\\') ++i;
            else if (c == '"') in_str = false;
        } else if (c == '"') {
            in_str = true;
        } else if (c == '{') {
            ++depth;
        } else if (c == '}') {
            if (--depth == 0) { *out = region.substr(open, i - open + 1); return true; }
        }
    }
    return false;
}

// ---------------------------------------------------------------- 配置

struct Config {
    long long app_id = 0;
    std::string version;
    std::string entry_point;
    std::string server_base_url;
    std::string updater_executable;
    std::string artifact_public_key;   // 受信构件公钥（client-release-2026-01）
};

bool load_config(const std::filesystem::path& exe_dir, Config* cfg) {
    std::filesystem::path path = exe_dir / "client-update.json";
    std::ifstream f(path, std::ios::binary);
    if (!f) { printf("[错误] 无法读取配置: %s\n", wide_to_utf8(path.wstring()).c_str()); return false; }
    std::stringstream ss; ss << f.rdbuf();
    std::string text = ss.str();

    long long id = 0;
    std::string v;
    if (!find_number(text, "appId", &id) || !find_string(text, "version", &v)) {
        printf("[错误] client-update.json 缺少 appId/version\n");
        return false;
    }
    cfg->app_id = id;
    cfg->version = v;
    find_string(text, "entryPoint", &cfg->entry_point);
    find_string(text, "updaterExecutable", &cfg->updater_executable);
    if (cfg->updater_executable.empty()) cfg->updater_executable = "pdk_updater.exe";
    find_string(text, "serverBaseUrl", &cfg->server_base_url);
    // 环境变量可覆盖服务端地址（与 Python 版一致）
    std::string env_base = getenv_str("PDK_UPDATE_BASE_URL");
    if (!env_base.empty()) cfg->server_base_url = env_base;
    while (!cfg->server_base_url.empty() && cfg->server_base_url.back() == '/')
        cfg->server_base_url.pop_back();

    std::string keys_obj;
    if (find_object(text, "artifactPublicKeys", &keys_obj)) {
        // 取第一个键值对作为受信公钥（测试程序只有一个 key）
        std::string::size_type colon = keys_obj.find(':');
        if (colon != std::string::npos) {
            std::string::size_type q1 = keys_obj.find('"', colon);
            std::string::size_type q2 = keys_obj.find('"', q1 + 1);
            if (q1 != std::string::npos && q2 != std::string::npos)
                cfg->artifact_public_key = keys_obj.substr(q1 + 1, q2 - q1 - 1);
        }
    }
    if (cfg->entry_point.empty() || cfg->server_base_url.empty() || cfg->artifact_public_key.empty()) {
        printf("[错误] 配置缺少 entryPoint/serverBaseUrl/artifactPublicKeys\n");
        return false;
    }
    return true;
}

// ---------------------------------------------------------------- 健康握手

void write_health_file() {
    std::string file = getenv_str("PDK_UPDATE_HEALTH_FILE");
    std::string nonce = getenv_str("PDK_UPDATE_HEALTH_NONCE");
    if (file.empty() || nonce.empty()) return;
    // version 从健康文件同目录约定不可得，直接用环境变量；测试程序由升级器只要求 version+nonce
    // 这里回读 client-update.json 的 version（更新后已是新版配置）
    char exe_path[MAX_PATH] = {0};
    GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
    std::filesystem::path exe_dir = std::filesystem::path(exe_path).parent_path();
    std::ifstream f(exe_dir / "client-update.json", std::ios::binary);
    std::stringstream ss; ss << f.rdbuf();
    std::string version;
    find_string(ss.str(), "version", &version);

    std::string payload = "{\"version\":\"" + json_escape(version) +
                          "\",\"nonce\":\"" + json_escape(nonce) +
                          "\",\"timestamp\":" + std::to_string((long long)time(nullptr)) + "}";
    std::filesystem::path target = std::filesystem::path(file);
    std::filesystem::path tmp = target;
    tmp += ".tmp";
    std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
    out << payload;
    out.close();
    if (MoveFileExW(tmp.wstring().c_str(), target.wstring().c_str(), MOVEFILE_REPLACE_EXISTING)) {
        printf("[升级器] 健康握手已写入: %s (version=%s)\n", file.c_str(), version.c_str());
    } else {
        printf("[升级器] 健康握手写入失败: %s (GLE=%lu)\n", file.c_str(), GetLastError());
    }
}

// ---------------------------------------------------------------- HTTP (WinHTTP)

struct HttpUrl {
    std::wstring host;
    std::wstring path;
    INTERNET_PORT port = 443;
    bool https = true;
};

bool crack_url(const std::string& url_utf8, HttpUrl* out) {
    std::wstring url = utf8_to_wide(url_utf8);
    URL_COMPONENTS c{};
    c.dwStructSize = sizeof(c);
    wchar_t host[512] = {0}, path[2048] = {0};
    c.lpszHostName = host; c.dwHostNameLength = 511;
    c.lpszUrlPath = path; c.dwUrlPathLength = 2047;
    if (!WinHttpCrackUrl(url.c_str(), (DWORD)url.size(), 0, &c)) return false;
    out->host = host;
    out->path = path;
    out->port = c.nPort;
    out->https = (c.nScheme == INTERNET_SCHEME_HTTPS);
    return true;
}

struct HttpSession {
    HINTERNET session = nullptr;
    HINTERNET connect = nullptr;
    ~HttpSession() {
        if (connect) WinHttpCloseHandle(connect);
        if (session) WinHttpCloseHandle(session);
    }
};

bool open_session(const HttpUrl& url, HttpSession* s) {
    s->session = WinHttpOpen(L"PDK-UpdateTester/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                             WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!s->session) return false;
    // 跟随重定向（下载地址可能 302 到对象存储）
    DWORD policy = WINHTTP_OPTION_REDIRECT_POLICY_ALWAYS;
    WinHttpSetOption(s->session, WINHTTP_OPTION_REDIRECT_POLICY, &policy, sizeof(policy));
    WinHttpSetTimeouts(s->session, 10000, 10000, 30000, 60000);
    s->connect = WinHttpConnect(s->session, url.host.c_str(), url.port, 0);
    return s->connect != nullptr;
}

struct HttpResponse {
    DWORD status = 0;
    std::string body;
    bool ok() const { return status == 200 || status == 206; }
};

// headers 额外请求头（可为空）；body_out 为空时丢弃响应体（用于大文件下载到回调）
bool http_request(const HttpSession& s, const HttpUrl& url, const wchar_t* verb,
                  const std::string& extra_headers, HttpResponse* resp,
                  bool (*chunk_cb)(void*, const char*, DWORD) = nullptr, void* cb_ctx = nullptr) {
    HINTERNET req = WinHttpOpenRequest(s.connect, verb, url.path.c_str(), nullptr,
                                       WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                       url.https ? WINHTTP_FLAG_SECURE : 0);
    if (!req) return false;
    std::wstring headers = utf8_to_wide(extra_headers);
    BOOL sent = WinHttpSendRequest(req, headers.empty() ? WINHTTP_NO_ADDITIONAL_HEADERS : headers.c_str(),
                                   (DWORD)headers.size(), WINHTTP_NO_REQUEST_DATA, 0, 0, 0);
    if (!sent || !WinHttpReceiveResponse(req, nullptr)) {
        WinHttpCloseHandle(req);
        return false;
    }
    DWORD status = 0, size = sizeof(status);
    WinHttpQueryHeaders(req, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                        WINHTTP_HEADER_NAME_BY_INDEX, &status, &size, WINHTTP_HEADER_NAME_BY_INDEX);
    resp->status = status;

    char buf[64 * 1024];
    for (;;) {
        DWORD available = 0;
        if (!WinHttpQueryDataAvailable(req, &available)) break;
        if (available == 0) break;
        DWORD to_read = available < sizeof(buf) ? available : sizeof(buf);
        DWORD read = 0;
        if (!WinHttpReadData(req, buf, to_read, &read) || read == 0) break;
        if (chunk_cb) {
            if (!chunk_cb(cb_ctx, buf, read)) { WinHttpCloseHandle(req); return false; }
        } else {
            resp->body.append(buf, read);
        }
    }
    WinHttpCloseHandle(req);
    return true;
}

std::string common_headers(const Config& cfg, const std::string& device_id) {
    return "X-PDK-App-ID: " + std::to_string(cfg.app_id) + "\r\n"
           "X-PDK-Device-ID: " + device_id + "\r\n"
           "User-Agent: PDK-UpdateTester/" + cfg.version + "\r\n";
}

// ---------------------------------------------------------------- SHA-256 (BCrypt)

std::string sha256_file_hex(const std::filesystem::path& path) {
    BCRYPT_ALG_HANDLE alg = nullptr;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) return {};
    BCRYPT_HASH_HANDLE hash = nullptr;
    DWORD hash_len = 0, done = 0, cb = sizeof(DWORD);
    BCryptGetProperty(alg, BCRYPT_HASH_LENGTH, (PUCHAR)&hash_len, sizeof(hash_len), &done, 0);
    std::vector<BYTE> hash_obj(hash_len * 4);
    if (BCryptCreateHash(alg, &hash, hash_obj.data(), (ULONG)hash_obj.size(), nullptr, 0, 0) < 0) {
        BCryptCloseAlgorithmProvider(alg, 0);
        return {};
    }
    std::vector<char> buffer(1024 * 1024);  // 堆缓冲，勿放栈上
    std::ifstream f(path, std::ios::binary);
    while (f) {
        f.read(buffer.data(), (std::streamsize)buffer.size());
        std::streamsize n = f.gcount();
        if (n > 0) BCryptHashData(hash, (PUCHAR)buffer.data(), (ULONG)n, 0);
    }
    std::vector<BYTE> digest(hash_len);
    BCryptFinishHash(hash, digest.data(), hash_len, 0);
    BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(alg, 0);
    static const char* hexd = "0123456789abcdef";
    std::string hex(hash_len * 2, '0');
    for (DWORD i = 0; i < hash_len; ++i) {
        hex[i * 2] = hexd[digest[i] >> 4];
        hex[i * 2 + 1] = hexd[digest[i] & 0xF];
    }
    return hex;
}

std::string random_nonce_hex() {
    BCRYPT_ALG_HANDLE alg = nullptr;
    BYTE raw[16] = {0};
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_RNG_ALGORITHM, nullptr, 0) == 0) {
        BCryptGenRandom(alg, raw, sizeof(raw), 0);
        BCryptCloseAlgorithmProvider(alg, 0);
    }
    static const char* hexd = "0123456789abcdef";
    std::string hex(sizeof(raw) * 2, '0');
    for (int i = 0; i < (int)sizeof(raw); ++i) {
        hex[i * 2] = hexd[raw[i] >> 4];
        hex[i * 2 + 1] = hexd[raw[i] & 0xF];
    }
    return hex;
}

// ---------------------------------------------------------------- 下载

struct DownloadCtx {
    std::ofstream file;
    long long total = 0;      // 期望大小
    long long received = 0;   // 含续传前已有的
    long long next_report = 0;
    bool aborted = false;
};

bool download_chunk(void* ctx, const char* data, DWORD size) {
    DownloadCtx* c = (DownloadCtx*)ctx;
    c->file.write(data, size);
    if (!c->file) { c->aborted = true; return false; }
    c->received += size;
    if (c->received >= c->next_report) {
        printf("    已下载 %.1f / %.1f MB\n", c->received / 1048576.0, c->total / 1048576.0);
        c->next_report = c->received + 4 * 1024 * 1024;
    }
    return true;
}

// ---------------------------------------------------------------- 主流程

void print_usage_line(const char* step) {
    printf("\n==============================\n%s\n", step);
}

int fail_exit() {
    printf("\n按回车退出...");
    (void)getchar();
    return 1;
}

}  // namespace

static int run_flow() {
    SetConsoleOutputCP(65001);  // 控制台按 UTF-8 输出（源码 /utf-8 编译）

    char exe_path[MAX_PATH] = {0};
    GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
    std::filesystem::path exe_dir = std::filesystem::path(exe_path).parent_path();

    printf("PDK 客户端升级测试程序（C++ 原生 + pdk_updater）\n");

    // 1) 健康握手：被升级器拉起的新版会带这两个环境变量
    write_health_file();

    // 2) 配置
    Config cfg;
    if (!load_config(exe_dir, &cfg)) return fail_exit();
    std::string device_id = getenv_str("COMPUTERNAME");
    if (device_id.empty()) device_id = "tester-device";
    printf("配置: appId=%lld version=%s entry=%s server=%s\n",
           cfg.app_id, cfg.version.c_str(), cfg.entry_point.c_str(), cfg.server_base_url.c_str());
    printf("设备: %s\n", device_id.c_str());

    // 3) check
    print_usage_line("步骤 1/3：查询升级服务器 check 接口");
    std::string check_url = cfg.server_base_url +
        "/api/v1/client/updates/check?currentVersion=" + cfg.version +
        "&platform=WINDOWS&arch=X64&channel=STABLE&protocolVersion=1&updaterVersion=1.0.0";
    HttpUrl url;
    if (!crack_url(check_url, &url)) { printf("[错误] URL 解析失败: %s\n", check_url.c_str()); return fail_exit(); }
    {
        HttpSession s;
        if (!open_session(url, &s)) { printf("[错误] WinHTTP 初始化失败 (GLE=%lu)\n", GetLastError()); return fail_exit(); }
        HttpResponse resp;
        if (!http_request(s, url, L"GET", common_headers(cfg, device_id), &resp) || !resp.ok()) {
            printf("[错误] check 请求失败 status=%lu body=%s\n", resp.status, resp.body.substr(0, 300).c_str());
            return fail_exit();
        }

        // 解析 data
        std::string data_obj, server_msg;
        find_string(resp.body, "message", &server_msg);
        if (!find_object(resp.body, "data", &data_obj) || data_obj.empty() || data_obj == "null") {
            printf("[错误] 服务端返回异常: %s\n", server_msg.c_str());
            printf("（若提示 appId 对应业务不存在，请先在后台创建该应用并配置升级策略）\n");
            return fail_exit();
        }
        bool has_update = data_obj.find("\"hasUpdate\":true") != std::string::npos;
        std::string policy;
        find_string(data_obj, "updatePolicy", &policy);
        printf("服务端响应: hasUpdate=%s updatePolicy=%s\n", has_update ? "true" : "false", policy.c_str());
        if (!has_update) {
            printf("\n✅ 当前已是最新版本，无需升级。按回车退出...");
            (void)getchar();
            return 0;
        }

        std::string target_version, check_request_id, event_token, artifact_obj;
        find_string(data_obj, "targetVersion", &target_version);
        find_string(data_obj, "checkRequestId", &check_request_id);
        find_string(data_obj, "eventToken", &event_token);
        if (!find_object(data_obj, "artifact", &artifact_obj) || artifact_obj.empty()) {
            printf("[错误] hasUpdate=true 但响应缺少 artifact\n");
            return fail_exit();
        }
        long long artifact_id = 0, file_size = 0;
        std::string download_url, sha256, signature, signing_key_id, package_type;
        find_number(artifact_obj, "artifactId", &artifact_id);
        find_number(artifact_obj, "fileSize", &file_size);
        find_string(artifact_obj, "downloadUrl", &download_url);
        find_string(artifact_obj, "sha256", &sha256);
        find_string(artifact_obj, "signature", &signature);
        find_string(artifact_obj, "signingKeyId", &signing_key_id);
        find_string(artifact_obj, "packageType", &package_type);
        printf("发现新版本 %s (artifactId=%lld, %.2f MB)\n",
               target_version.c_str(), artifact_id, file_size / 1048576.0);
        if (download_url.empty() || file_size <= 0 || signature.empty() || artifact_id <= 0) {
            printf("[错误] artifact 字段不完整\n");
            return fail_exit();
        }
        if (sha256.size() != 64 || package_type != "ZIP") {
            printf("[错误] 不支持的构件类型: %s\n", package_type.c_str());
            return fail_exit();
        }

        printf("\n是否立即升级到 %s？(Y=升级 / 其他=退出) ", target_version.c_str());
        char answer[16] = {0};
        (void)fgets(answer, sizeof(answer), stdin);
        if (answer[0] != 'Y' && answer[0] != 'y') return 0;

        // 4) 下载（断点续传）
        print_usage_line("步骤 2/3：下载升级包（支持断点续传）");
        std::filesystem::path cache_dir = getenv_str("LOCALAPPDATA");
        if (cache_dir.empty()) cache_dir = exe_dir;
        cache_dir /= "PDK"; cache_dir /= "updates"; cache_dir /= "cache";
        std::filesystem::create_directories(cache_dir);
        std::filesystem::path pkg = cache_dir / ("artifact-" + std::to_string(artifact_id) + ".zip");

        long long existing = 0;
        if (std::filesystem::exists(pkg)) existing = (long long)std::filesystem::file_size(pkg);
        if (existing == file_size) {
            printf("本地已有完整包，跳过下载\n");
        } else {
            if (existing > file_size || existing < 0) existing = 0;
            std::string dl_headers = common_headers(cfg, device_id);
            if (existing > 0) {
                printf("从断点续传: 已有 %lld bytes\n", existing);
                dl_headers += "Range: bytes=" + std::to_string(existing) + "-\r\n";
            }
            HttpUrl dl;
            if (!crack_url(download_url, &dl)) { printf("[错误] 下载 URL 解析失败\n"); return fail_exit(); }
            HttpSession ds;
            if (!open_session(dl, &ds)) { printf("[错误] WinHTTP 初始化失败\n"); return fail_exit(); }
            DownloadCtx ctx;
            ctx.total = file_size;
            if (existing > 0) ctx.received = existing;
            ctx.file.open(pkg, std::ios::binary | std::ios::app);
            if (!ctx.file) { printf("[错误] 无法写入 %s\n", wide_to_utf8(pkg.wstring()).c_str()); return fail_exit(); }
            HttpResponse dl_resp;
            bool ok = http_request(ds, dl, L"GET", dl_headers, &dl_resp, download_chunk, &ctx);
            ctx.file.close();
            if (!ok || ctx.aborted || (dl_resp.status != 200 && dl_resp.status != 206)) {
                printf("[错误] 下载失败 status=%lu（部分文件已保留，重试可续传）\n", dl_resp.status);
                return fail_exit();
            }
            if (dl_resp.status == 200) {
                // 服务端不支持 Range，全量重下覆盖
                printf("服务端返回 200（不支持续传），全量下载完成\n");
                if ((long long)std::filesystem::file_size(pkg) != file_size) {
                    printf("[错误] 文件大小不匹配\n");
                    return fail_exit();
                }
            }
        }
        if ((long long)std::filesystem::file_size(pkg) != file_size) {
            printf("[错误] 下载不完整: %lld / %lld\n",
                   (long long)std::filesystem::file_size(pkg), file_size);
            return fail_exit();
        }

        // SHA-256 校验（真正的 Ed25519 验签由 pdk_updater 做）
        print_usage_line("步骤 3/3：校验并拉起原生升级器 pdk_updater.exe");
        printf("计算 SHA-256...\n");
        {
            std::string digest = sha256_file_hex(pkg);
            if (digest != sha256) {
                printf("[错误] SHA-256 不匹配!\n  期望: %s\n  实际: %s\n", sha256.c_str(), digest.c_str());
                std::filesystem::remove(pkg);
                return fail_exit();
            }
            printf("SHA-256 校验通过\n");
        }

        // 5) 组装 job.json，复制升级器到运行目录（不能从 install_root 直接跑，否则镜像锁住目录）
        std::filesystem::path run_dir = cache_dir.parent_path() / ("updater-run-" + std::to_string(GetCurrentProcessId()));
        std::error_code ec;
        std::filesystem::remove_all(run_dir, ec);
        std::filesystem::create_directories(run_dir, ec);
        std::filesystem::path updater_src = exe_dir / cfg.updater_executable;
        std::filesystem::path updater_exe = run_dir / cfg.updater_executable;
        if (!CopyFileW(updater_src.wstring().c_str(), updater_exe.wstring().c_str(), FALSE)) {
            printf("[错误] 复制升级器失败: %s (GLE=%lu)\n",
                   wide_to_utf8(updater_src.wstring()).c_str(), GetLastError());
            return fail_exit();
        }
        std::filesystem::path health_file = cache_dir.parent_path() /
            ("health-" + std::to_string(GetCurrentProcessId()) + ".json");
        std::filesystem::remove(health_file, ec);
        std::string nonce = random_nonce_hex();

        std::ostringstream job;
        job << "{\n"
            << "  \"schemaVersion\": 1,\n"
            << "  \"packagePath\": \"" << json_escape(wide_to_utf8(pkg.wstring())) << "\",\n"
            << "  \"installRoot\": \"" << json_escape(wide_to_utf8(exe_dir.wstring())) << "\",\n"
            << "  \"targetVersion\": \"" << json_escape(target_version) << "\",\n"
            << "  \"entryPoint\": \"" << json_escape(cfg.entry_point) << "\",\n"
            << "  \"appId\": " << cfg.app_id << ",\n"
            << "  \"platform\": \"WINDOWS\",\n"
            << "  \"arch\": \"X64\",\n"
            << "  \"packageType\": \"" << json_escape(package_type) << "\",\n"
            << "  \"fileSize\": " << file_size << ",\n"
            << "  \"sha256\": \"" << json_escape(sha256) << "\",\n"
            << "  \"signature\": \"" << json_escape(signature) << "\",\n"
            << "  \"publicKey\": \"" << json_escape(cfg.artifact_public_key) << "\",\n"
            << "  \"parentPid\": " << GetCurrentProcessId() << ",\n"
            << "  \"healthFile\": \"" << json_escape(wide_to_utf8(health_file.wstring())) << "\",\n"
            << "  \"healthNonce\": \"" << json_escape(nonce) << "\",\n"
            << "  \"healthTimeoutSeconds\": 45,\n"
            << "  \"relaunchOnRollback\": true,\n"
            << "  \"telemetry\": {\n"
            << "    \"endpoint\": \"" << json_escape(cfg.server_base_url) << "\",\n"
            << "    \"appId\": " << cfg.app_id << ",\n"
            << "    \"deviceId\": \"" << json_escape(device_id) << "\",\n"
            << "    \"checkRequestId\": \"" << json_escape(check_request_id) << "\",\n"
            << "    \"eventToken\": \"" << json_escape(event_token) << "\",\n"
            << "    \"artifactId\": " << artifact_id << ",\n"
            << "    \"fromVersion\": \"" << json_escape(cfg.version) << "\",\n"
            << "    \"targetVersion\": \"" << json_escape(target_version) << "\",\n"
            << "    \"platform\": \"WINDOWS\"\n"
            << "  }\n"
            << "}\n";
        std::filesystem::path job_file = run_dir / "job.json";
        {
            std::ofstream jf(job_file, std::ios::binary | std::ios::trunc);
            jf << job.str();
        }
        printf("job.json 已生成: %s\n", wide_to_utf8(job_file.wstring()).c_str());

        // 6) 拉起升级器并立即退出
        std::string cmd = "\"" + wide_to_utf8(updater_exe.wstring()) + "\" --job \"" +
                          wide_to_utf8(job_file.wstring()) + "\"";
        STARTUPINFOA si{};
        si.cb = sizeof(si);
        PROCESS_INFORMATION pi{};
        if (!CreateProcessA(nullptr, cmd.data(), nullptr, nullptr, FALSE,
                            CREATE_NO_WINDOW, nullptr,
                            wide_to_utf8(run_dir.wstring()).c_str(), &si, &pi)) {
            printf("[错误] 启动升级器失败 (GLE=%lu)\n", GetLastError());
            return fail_exit();
        }
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        printf("升级器已启动（安装日志: %%LOCALAPPDATA%%\\PDK\\updates\\native-updater-日期.log）\n");
        printf("本程序即将退出，升级器将在父进程退出后执行安装...\n");
        Sleep(800);
        return 0;
    }
    return fail_exit();
}

int wmain() {
    SetConsoleOutputCP(65001);
    return run_flow();
}
