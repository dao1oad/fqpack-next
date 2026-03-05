#include "log.h"
#include <chrono>
#include <iostream> // cout
#include <iomanip> // put_time,chrono

#ifndef _WIN32
#include <unistd.h>
#endif

std::ofstream Log::fout_{};
std::mutex Log::mutex_{};

namespace {
std::string logFile = "./log.log";

auto GetFormatTime(tm& t)->decltype(std::put_time(nullptr, "")) {
	auto curTime = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
#ifdef _WIN32
	localtime_s(&t, &curTime);
#else
	localtime_r(&curTime, &t);
#endif
	return std::put_time(&t, "%F %T");
}

const char* GetFileName(const char* cp) {
#ifdef _WIN32
	const char* tmp = strrchr(cp, '\\'); // reverse lookup separator
#else
	const char* tmp = strrchr(cp, '/');
#endif
	return tmp ? tmp + 1 : cp;
}
}

std::ostringstream& Log::Process(const char* level, const char* fileName, int lineNum, const char* funcName) 
{
	struct tm t;
	osstream_ << "[" << level << "]"
		<< "[" << GetFormatTime(t) << "]"
		<< "[tid " << std::this_thread::get_id() << "]"
		<< "[" << GetFileName(fileName) << "]"
		<< "[" << funcName << ":" << lineNum << "] ";
	return osstream_;
}

void Log::SetSaveLogFilePath(const std::string& path)
{
	logFile = path;
}

Log::~Log()
{
	std::unique_lock<std::mutex> lock(mutex_);
	std::cout << osstream_.str() << std::endl;
	fout_.open(logFile, std::ofstream::app);
	fout_ << osstream_.str() << std::endl;
	fout_.close();
}
