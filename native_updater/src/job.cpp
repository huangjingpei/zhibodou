#include "job.hpp"

#include <nlohmann/json.hpp>

#include <fstream>
#include <regex>

namespace pdk {
namespace {

using json = nlohmann::json;

std::string required_string(const json& source, const char* name) {
    if (!source.contains(name) || !source[name].is_string() || source[name].get<std::string>().empty()) {
        throw UpdateError(std::string("job missing string field: ") + name);
    }
    return source[name].get<std::string>();
}

bool safe_relative_path(const std::string& raw) {
    const auto path = path_from_utf8(raw);
    if (path.empty() || path.is_absolute() || path.has_root_name()) return false;
    for (const auto& part : path) {
        if (part == L".." || part == L".") return false;
    }
    return true;
}

}  // namespace

UpdateJob load_job(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw UpdateError("cannot open updater job: " + path_to_utf8(path));
    json raw;
    try {
        input >> raw;
    } catch (const json::exception& error) {
        throw UpdateError(std::string("invalid updater job JSON: ") + error.what());
    }

    UpdateJob job;
    try {
        job.schema_version = raw.value("schemaVersion", 0);
        job.package_path = path_from_utf8(required_string(raw, "packagePath"));
        job.install_root = path_from_utf8(required_string(raw, "installRoot"));
        job.target_version = required_string(raw, "targetVersion");
        job.entry_point = required_string(raw, "entryPoint");
        job.app_id = raw.at("appId").get<int64_t>();
        job.platform = required_string(raw, "platform");
        job.arch = required_string(raw, "arch");
        job.package_type = required_string(raw, "packageType");
        job.file_size = raw.at("fileSize").get<uint64_t>();
        job.sha256 = required_string(raw, "sha256");
        job.signature = required_string(raw, "signature");
        job.public_key = required_string(raw, "publicKey");
        job.parent_pid = raw.value("parentPid", 0U);
        job.health_file = path_from_utf8(required_string(raw, "healthFile"));
        job.health_nonce = required_string(raw, "healthNonce");
        job.health_timeout_seconds = raw.value("healthTimeoutSeconds", 45U);
        job.relaunch_on_rollback = raw.value("relaunchOnRollback", true);
        if (raw.contains("telemetry") && raw["telemetry"].is_object()) {
            const auto& value = raw["telemetry"];
            TelemetryJob telemetry;
            telemetry.endpoint = required_string(value, "endpoint");
            telemetry.app_id = value.at("appId").get<int64_t>();
            telemetry.device_id = required_string(value, "deviceId");
            telemetry.check_request_id = required_string(value, "checkRequestId");
            telemetry.event_token = required_string(value, "eventToken");
            if (value.contains("artifactId") && !value["artifactId"].is_null()) {
                telemetry.artifact_id = value["artifactId"].get<int64_t>();
            }
            telemetry.from_version = required_string(value, "fromVersion");
            telemetry.target_version = required_string(value, "targetVersion");
            telemetry.platform = required_string(value, "platform");
            job.telemetry = std::move(telemetry);
        }
    } catch (const json::exception& error) {
        throw UpdateError(std::string("updater job field type error: ") + error.what());
    }
    validate_job(job);
    return job;
}

void validate_job(const UpdateJob& job) {
    static const std::regex version_pattern(R"(^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$)");
    static const std::regex sha_pattern(R"(^[0-9a-fA-F]{64}$)");
    if (job.schema_version != 1) throw UpdateError("unsupported updater job schemaVersion");
    if (job.app_id <= 0 || job.file_size == 0) throw UpdateError("invalid appId or fileSize");
    if (!std::regex_match(job.target_version, version_pattern)) throw UpdateError("invalid targetVersion");
    if (!std::regex_match(job.sha256, sha_pattern)) throw UpdateError("invalid SHA-256 value");
    if (job.platform != "WINDOWS" || job.arch != "X64" || job.package_type != "ZIP") {
        throw UpdateError("this updater only accepts WINDOWS/X64/ZIP artifacts");
    }
    if (!safe_relative_path(job.entry_point)) throw UpdateError("entryPoint must be a safe relative path");
    if (!job.package_path.is_absolute() || !job.install_root.is_absolute() || !job.health_file.is_absolute()) {
        throw UpdateError("packagePath, installRoot and healthFile must be absolute paths");
    }
    if (job.install_root == job.install_root.root_path()) throw UpdateError("refusing to replace a drive root");
    if (job.health_timeout_seconds < 10 || job.health_timeout_seconds > 300) {
        throw UpdateError("healthTimeoutSeconds must be between 10 and 300");
    }
    if (job.health_nonce.size() < 16 || job.health_nonce.size() > 128) {
        throw UpdateError("healthNonce length is invalid");
    }
    if (job.telemetry && (job.telemetry->app_id != job.app_id ||
                          job.telemetry->target_version != job.target_version)) {
        throw UpdateError("telemetry scope does not match updater job");
    }
}

}  // namespace pdk
