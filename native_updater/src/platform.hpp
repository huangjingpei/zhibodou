#pragma once

#include "job.hpp"

#include <windows.h>

#include <filesystem>
#include <string>

namespace pdk {

enum class SwitchStrategy { Atomic, InPlace };

void log_line(const std::string& message);
void kill_process_tree(uint32_t root_pid);
void rename_with_retry(const std::filesystem::path& from, const std::filesystem::path& to,
                       const char* operation, int tries = 3);
void sync_tree(const std::filesystem::path& src, const std::filesystem::path& dst, const char* label);
SwitchStrategy switch_to_new_version(const std::filesystem::path& install_root,
                                     const std::filesystem::path& stage,
                                     const std::filesystem::path& backup);
bool wait_for_process_exit(uint32_t pid, uint32_t timeout_seconds);
PROCESS_INFORMATION launch_client(const std::filesystem::path& root, const std::string& entry_point,
                                  const std::filesystem::path* health_file,
                                  const std::string* health_nonce);
bool wait_for_health(PROCESS_INFORMATION& process, const UpdateJob& job);
void terminate_process(PROCESS_INFORMATION& process);
std::filesystem::path choose_job_file();
void show_result(bool success, const std::string& message);
std::string unique_suffix();

}  // namespace pdk
