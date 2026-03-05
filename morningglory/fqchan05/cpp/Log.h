#pragma once

#include <fstream> // ofstream
#include <sstream> // ostringstream
#include <mutex> // mutex

class Log {
public:
	std::ostringstream& Process(const char* level, const char* fileName, int lineNum, const char* funcName);
	void SetSaveLogFilePath(const std::string& path);
	~Log();
private:
	static std::ofstream fout_;
	static std::mutex mutex_;
	std::ostringstream osstream_;
};

#define LogInfo  Log().Process("Info ", __FILE__, __LINE__, __func__)
#define LogDebug Log().Process("Debug", __FILE__, __LINE__, __func__)
#define LogWarn  Log().Process("Warn ", __FILE__, __LINE__, __func__)
#define LogError Log().Process("Error", __FILE__, __LINE__, __func__)
#define LogFatal Log().Process("Fatal", __FILE__, __LINE__, __func__)
