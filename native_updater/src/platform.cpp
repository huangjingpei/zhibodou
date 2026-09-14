#include "platform.hpp"

#include <commdlg.h>
#include <nlohmann/json.hpp>
#include <shlobj.h>
#include <tlhelp32.h>

#include <chrono>
#include <ctime>
#include <fstream>
#include <map>
#include <set>
#include <thread>
#include <vector>

namespace pdk {

void log_line(const std::string& message) {
    try {
        PWSTR local = nullptr;
        if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &local))) return;
        const std::filesystem::path dir = std::filesystem::path(local) / L"PDK" / L"updates";
        CoTaskMemFree(local);
        std::error_code ec;
        std::filesystem::create_directories(dir, ec);
        const auto now = std::chrono::system_clock::now();
        std::time_t seconds = std::chrono::system_clock::to_time_t(now);
        std::tm parts{};
        localtime_s(&parts, &seconds);
        char stamp[32];
        std::strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%S", &parts);
        char day[16];
        std::strftime(day, sizeof(day), "%Y%m%d", &parts);
        const std::string day_str(day);
        std::ofstream file(dir / (L"native-updater-" +
                                  std::wstring(day_str.begin(), day_str.end()) + L".log"),
                           std::ios::app);
        file << "[" << stamp << "] [PDK-Native-Updater] " << message << "\n";
    } catch (...) {
        // 日志失败不能影响升级事务。
    }
}

void kill_process_tree(uint32_t root_pid) {
    if (root_pid == 0) return;  // 无有效父进程，无需清理
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return;
    std::map<uint32_t, std::vector<uint32_t>> children;
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    if (Process32FirstW(snapshot, &entry)) {
        do {
            children[entry.th32ParentProcessID].push_back(entry.th32ProcessID);
        } while (Process32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);

    const auto descendants = [&children](uint32_t pid) {
        std::set<uint32_t> out;
        std::vector<uint32_t> queue{pid};
        while (!queue.empty()) {
            const uint32_t current = queue.back();
            queue.pop_back();
            const auto found = children.find(current);
            if (found == children.end()) continue;
            for (const uint32_t child : found->second) {
                if (out.insert(child).second) queue.push_back(child);
            }
        }
        return out;
    };

    std::map<uint32_t, uint32_t> parent_of;
    for (const auto& [parent, kids] : children) {
        for (const uint32_t kid : kids) parent_of[kid] = parent;
    }

    // 保护集 = 升级器自身 + 其子孙 + 其祖先链（onefile/引导进程同理），
    // 并只清理主程序的"其他"子孙；主程序自身退出交给 wait_for_process_exit。
    const uint32_t self_pid = GetCurrentProcessId();
    std::set<uint32_t> protected_set = descendants(self_pid);
    protected_set.insert(self_pid);
    auto cursor = parent_of.find(self_pid);
    while (cursor != parent_of.end() && cursor->second != 0 &&
           protected_set.insert(cursor->second).second) {
        cursor = parent_of.find(cursor->second);
    }

    std::set<uint32_t> to_kill = descendants(root_pid);
    for (const uint32_t pid : protected_set) to_kill.erase(pid);
    int killed = 0;
    for (const uint32_t pid : to_kill) {
        HANDLE process = OpenProcess(PROCESS_TERMINATE, FALSE, pid);
        if (!process) continue;
        if (TerminateProcess(process, 1)) ++killed;
        CloseHandle(process);
    }
    log_line("已尝试清理父进程树 root=" + std::to_string(root_pid) +
             " 待结束=" + std::to_string(to_kill.size()) + " 已结束=" + std::to_string(killed));
}

void rename_with_retry(const std::filesystem::path& from, const std::filesystem::path& to,
                       const char* operation, int tries) {
    std::error_code error;
    for (int attempt = 1; attempt <= tries; ++attempt) {
        std::filesystem::rename(from, to, error);
        if (!error) return;
        log_line(std::string(operation) + " 第 " + std::to_string(attempt) + "/" +
                 std::to_string(tries) + " 次失败：" + error.message());
        if (attempt < tries) std::this_thread::sleep_for(std::chrono::milliseconds(800 * attempt));
    }
    throw UpdateError(std::string(operation) + ": " + error.message());
}

namespace {

void collect_files(const std::filesystem::path& base, const std::filesystem::path& dir,
                   std::map<std::wstring, std::filesystem::path>& out) {
    std::error_code ec;
    for (const auto& item : std::filesystem::directory_iterator(dir, ec)) {
        std::error_code entry_ec;
        if (item.is_directory(entry_ec)) {
            collect_files(base, item.path(), out);
        } else {
            out[item.path().lexically_relative(base).wstring()] = item.path();
        }
    }
}

}  // namespace

void sync_tree(const std::filesystem::path& src, const std::filesystem::path& dst, const char* label) {
    std::map<std::wstring, std::filesystem::path> src_files;
    collect_files(src, src, src_files);
    if (src_files.empty()) throw UpdateError(std::string(label) + ": 新版本目录为空");
    for (const auto& [relative, from] : src_files) {
        const auto to = dst / relative;
        std::error_code ec;
        std::filesystem::create_directories(to.parent_path(), ec);
        std::filesystem::copy_file(from, to, std::filesystem::copy_options::overwrite_existing, ec);
        if (ec) {
            throw UpdateError(std::string(label) + ": 无法写入 " + path_to_utf8(relative) +
                              "（文件被占用，请关闭正在使用它的程序后重试）: " + ec.message());
        }
    }
    std::map<std::wstring, std::filesystem::path> dst_files;
    collect_files(dst, dst, dst_files);
    for (const auto& [relative, path] : dst_files) {
        if (src_files.count(relative)) continue;
        std::error_code ec;
        std::filesystem::remove(path, ec);  // 旧残留文件删除失败不影响升级
    }
}

SwitchStrategy switch_to_new_version(const std::filesystem::path& install_root,
                                     const std::filesystem::path& stage,
                                     const std::filesystem::path& backup) {
    try {
        rename_with_retry(install_root, backup, "原子替换失败（install_root.replace）", 3);
    } catch (const UpdateError&) {
        log_line("目录被占用，无法原子替换，改用逐文件就地同步");
        std::error_code ec;
        std::filesystem::remove_all(backup, ec);
        std::filesystem::create_directories(backup, ec);
        std::filesystem::copy(install_root, backup,
                              std::filesystem::copy_options::recursive |
                                  std::filesystem::copy_options::overwrite_existing, ec);
        if (ec) throw UpdateError("就地升级备份失败: " + ec.message());
        try {
            sync_tree(stage, install_root, "就地升级");
        } catch (...) {
            try {
                sync_tree(backup, install_root, "就地升级失败回滚");
            } catch (...) {
            }
            throw;
        }
        return SwitchStrategy::InPlace;
    }
    rename_with_retry(stage, install_root, "切换失败（stage.replace）", 3);
    return SwitchStrategy::Atomic;
}
namespace {

std::wstring quote(const std::wstring& value) {
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (const wchar_t c : value) {
        if (c == L'\\') {
            ++slashes;
        } else if (c == L'\"') {
            result.append(slashes * 2 + 1, L'\\');
            result.push_back(c);
            slashes = 0;
        } else {
            result.append(slashes, L'\\');
            slashes = 0;
            result.push_back(c);
        }
    }
    result.append(slashes * 2, L'\\');
    result.push_back(L'\"');
    return result;
}

bool health_matches(const UpdateJob& job) {
    try {
        std::ifstream input(job.health_file, std::ios::binary);
        if (!input) return false;
        nlohmann::json value;
        input >> value;
        return value.value("nonce", std::string{}) == job.health_nonce &&
               value.value("version", std::string{}) == job.target_version;
    } catch (...) {
        return false;
    }
}

}  // namespace

bool wait_for_process_exit(uint32_t pid, uint32_t timeout_seconds) {
    if (pid == 0) return true;
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!process) return GetLastError() == ERROR_INVALID_PARAMETER;
    const DWORD result = WaitForSingleObject(process, timeout_seconds * 1000U);
    CloseHandle(process);
    return result == WAIT_OBJECT_0;
}

PROCESS_INFORMATION launch_client(const std::filesystem::path& root, const std::string& entry_point,
                                  const std::filesystem::path* health_file,
                                  const std::string* health_nonce) {
    const auto executable = root / path_from_utf8(entry_point);
    if (!std::filesystem::is_regular_file(executable)) throw UpdateError("client entry point is missing");
    if (health_file && health_nonce) {
        SetEnvironmentVariableW(L"PDK_UPDATE_HEALTH_FILE", health_file->c_str());
        SetEnvironmentVariableW(L"PDK_UPDATE_HEALTH_NONCE", widen(*health_nonce).c_str());
    } else {
        SetEnvironmentVariableW(L"PDK_UPDATE_HEALTH_FILE", nullptr);
        SetEnvironmentVariableW(L"PDK_UPDATE_HEALTH_NONCE", nullptr);
    }
    std::wstring command = quote(executable.wstring());
    std::vector<wchar_t> mutable_command(command.begin(), command.end());
    mutable_command.push_back(L'\0');
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(executable.c_str(), mutable_command.data(), nullptr, nullptr, FALSE,
                        CREATE_UNICODE_ENVIRONMENT, nullptr, root.c_str(), &startup, &process)) {
        throw UpdateError(windows_error("cannot launch client"));
    }
    return process;
}

bool wait_for_health(PROCESS_INFORMATION& process, const UpdateJob& job) {
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::seconds(job.health_timeout_seconds);
    while (std::chrono::steady_clock::now() < deadline) {
        if (health_matches(job)) return true;
        if (WaitForSingleObject(process.hProcess, 0) == WAIT_OBJECT_0) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(400));
    }
    return health_matches(job);
}

void terminate_process(PROCESS_INFORMATION& process) {
    if (process.hProcess) {
        if (WaitForSingleObject(process.hProcess, 0) != WAIT_OBJECT_0) {
            TerminateProcess(process.hProcess, 70);
            WaitForSingleObject(process.hProcess, 10000);
        }
        CloseHandle(process.hProcess);
        process.hProcess = nullptr;
    }
    if (process.hThread) {
        CloseHandle(process.hThread);
        process.hThread = nullptr;
    }
}

std::filesystem::path choose_job_file() {
    std::vector<wchar_t> file(32768, L'\0');
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.lpstrFile = file.data();
    dialog.nMaxFile = static_cast<DWORD>(file.size());
    dialog.lpstrFilter = L"PDK Updater Job (*.json)\0*.json\0All files (*.*)\0*.*\0";
    dialog.lpstrTitle = L"Select an updater job JSON";
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_DONTADDTORECENT;
    if (!GetOpenFileNameW(&dialog)) return {};
    return std::filesystem::path(file.data());
}

void show_result(bool success, const std::string& message) {
    MessageBoxW(nullptr, widen(message).c_str(), success ? L"PDK Updater" : L"PDK Updater Error",
                MB_OK | (success ? MB_ICONINFORMATION : MB_ICONERROR) | MB_SETFOREGROUND);
}

std::string unique_suffix() {
    return std::to_string(GetCurrentProcessId()) + "-" + std::to_string(GetTickCount64());
}

}  // namespace pdk
