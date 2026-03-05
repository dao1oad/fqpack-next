cmake_minimum_required(VERSION 3.9)

message("current platform: ${CMAKE_HOST_SYSTEM_NAME}")

if(CMAKE_HOST_SYSTEM_NAME MATCHES "Windows")
    if($ENV{VCPKG_ROOT})
        message(FATAL_ERROR "not defined environment variable: VCPKG_ROOT")
    endif()
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake")
endif()

if(CMAKE_CL_64)
    add_compile_definitions(MAKE_X64)
    if(MAKE_DZH)
        add_compile_definitions(MAKE_DZH)
    endif()
endif()

project (fqchan05)

set (LIBRARY_NAME fqchan05)

set (FQCHAN05_VERSION_MAJOR 1)
set (FQCHAN05_VERSION_MINOR 0)

aux_source_directory(./cpp SRCS)

find_package(Poco REQUIRED COMPONENTS Foundation)
MESSAGE("Poco_INCLUDE_DIRS = ${Poco_INCLUDE_DIRS}")
MESSAGE("Poco_LIBRARIES = ${Poco_LIBRARIES}")
add_library(${LIBRARY_NAME} SHARED ${SRCS})

target_link_libraries(${LIBRARY_NAME} PRIVATE ${Poco_LIBRARIES})
