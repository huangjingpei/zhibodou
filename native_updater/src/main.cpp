#include "crypto.hpp"
#include "job.hpp"
#include "platform.hpp"
#include "telemetry.hpp"
#include "zip_install.hpp"

#include <windows.h>

#include <filesystem>
#include <iostream>
#include <string>
#include <system_error>

namespace {

struct Options {
    std::filesystem::path job_path;
    bool interactive{false};
    bool quiet{false};
};

Options parse_options(int argc, wchar_t** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::wstring arg = argv[i];
        if (arg == L"--job" && i + 1 < argc) options.job_path = argv[++i];
        else if (arg == L"--interactive") options.interactive = true;
        else if (arg == L"--quiet") options.quiet = true;
        else if (arg == L"--version") {
            std::cout << "pdk_updater " << PDK_UPDATER_VERSION << '\n';
            std::exit(0);
        } else if (arg == L"--help" || arg == L"-h") {
            std::cout << "Usage: pdk_updater.exe --job <absolute-job.json> [--quiet]\n"
                         "       pdk_updater.exe --interactive\n";
            std::exit(0);
        } else {
            throw pdk::UpdateError("unknown or incomplete command line option");
        }
    }
    if (argc == 1) options.interactive = true;
    if (options.interactive && options.job_path.empty()) options.job_path = pdk::choose_job_file();
    if (options.job_path.empty()) throw pdk::UpdateError("no updater job selected", 64);
    return options;
}

void remove_tree(const std::filesystem::path& path) noexcept {
    std::error_code ignored;
    std::filesystem::remove_all(path, ignored);
}

void rename_checked(const std::filesystem::path& from, const std::filesystem::path& to,
                    const char* operation) {
    std::error_code error;
    std::filesystem::rename(from, to, error);
    if (error) throw pdk::UpdateError(std::string(operation) + ": " + error.message());
}

int run_update(const pdk::UpdateJob& job) {
    pdk::verify_job_artifact(job);
    if (!pdk::wait_for_process_exit(job.parent_pid, 90)) {
        pdk::report_event(job, "INSTALL_FAILED", "MAIN_PROCESS_NOT_EXITED");
        throw pdk::UpdateError("parent client did not exit within 90 seconds", 65);
    }

    const auto parent = job.install_root.parent_path();
    const auto suffix = pdk::unique_suffix();
    const auto stage = parent / (L"." + job.install_root.filename().wstring() + L".update-" + pdk::widen(suffix));
    const auto backup = parent / (L"." + job.install_root.filename().wstring() + L".backup-" + pdk::widen(suffix));
    const auto failed = parent / (L"." + job.install_root.filename().wstring() + L".failed-" + pdk::widen(suffix));
    remove_tree(stage);
    remove_tree(failed);
    std::error_code ignored;
    std::filesystem::remove(job.health_file, ignored);

    bool old_moved = false;
    bool new_installed = false;
    try {
        std::filesystem::create_directories(stage);
        pdk::validate_and_extract(job, stage);
        rename_checked(job.install_root, backup, "cannot move current install to backup");
        old_moved = true;
        rename_checked(stage, job.install_root, "cannot activate staged install");
        new_installed = true;
        auto process = pdk::launch_client(job.install_root, job.entry_point,
                                          &job.health_file, &job.health_nonce);
        if (pdk::wait_for_health(process, job)) {
            if (process.hThread) CloseHandle(process.hThread);
            if (process.hProcess) CloseHandle(process.hProcess);
            pdk::report_event(job, "INSTALL_SUCCEEDED");
            remove_tree(backup);
            std::filesystem::remove(job.health_file, ignored);
            return 0;
        }
        pdk::terminate_process(process);
        rename_checked(job.install_root, failed, "cannot quarantine failed new install");
        new_installed = false;
        rename_checked(backup, job.install_root, "cannot restore previous install");
        old_moved = false;
        if (job.relaunch_on_rollback) {
            auto old_process = pdk::launch_client(job.install_root, job.entry_point, nullptr, nullptr);
            if (old_process.hThread) CloseHandle(old_process.hThread);
            if (old_process.hProcess) CloseHandle(old_process.hProcess);
        }
        remove_tree(failed);
        pdk::report_event(job, "INSTALL_FAILED", "HEALTH_CHECK_FAILED");
        throw pdk::UpdateError("new client failed health check; previous version restored", 70);
    } catch (...) {
        remove_tree(stage);
        if (old_moved) {
            try {
                if (new_installed && std::filesystem::exists(job.install_root)) {
                    rename_checked(job.install_root, failed, "cannot quarantine incomplete install");
                }
                if (!std::filesystem::exists(job.install_root) && std::filesystem::exists(backup)) {
                    rename_checked(backup, job.install_root, "cannot recover current install");
                }
                remove_tree(failed);
            } catch (...) {
                // 保留 backup/failed 目录供人工恢复，不覆盖原始异常。
            }
        }
        throw;
    }
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    SetConsoleOutputCP(CP_UTF8);
    bool interactive = argc == 1;
    try {
        const auto options = parse_options(argc, argv);
        interactive = options.interactive;
        const auto job = pdk::load_job(options.job_path);
        const int result = run_update(job);
        if (!options.quiet) std::cout << "PDK_UPDATE_OK version=" << job.target_version << '\n';
        if (interactive) pdk::show_result(true, "Update installed successfully: " + job.target_version);
        return result;
    } catch (const pdk::UpdateError& error) {
        std::cerr << "PDK_UPDATE_ERROR " << error.what() << '\n';
        if (interactive) pdk::show_result(false, error.what());
        return error.exit_code();
    } catch (const std::exception& error) {
        std::cerr << "PDK_UPDATE_ERROR " << error.what() << '\n';
        if (interactive) pdk::show_result(false, error.what());
        return 71;
    }
}
