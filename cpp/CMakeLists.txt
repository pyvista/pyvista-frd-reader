cmake_minimum_required(VERSION 3.16)
project(pvfrd LANGUAGES CXX)

option(PVFRD_BUILD_SHARED "Build a shared library (needed for the ctypes binding)" ON)
option(PVFRD_BUILD_TOOLS "Build the frd_dump conformance tool" ON)
option(PVFRD_BUILD_TESTS "Build the gtest suite" OFF)
option(PVFRD_BUILD_FUZZERS "Build libFuzzer targets (Clang only)" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Hide everything except what PVFRD_API marks, so the shared object exports
# exactly the documented C ABI and nothing else. A binding that can only see
# the documented symbols cannot accidentally depend on an internal one.
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)

set(PVFRD_SOURCES src/parse.cpp src/derived.cpp src/api.cpp)

if(PVFRD_BUILD_SHARED)
  add_library(pvfrd SHARED ${PVFRD_SOURCES})
  target_compile_definitions(pvfrd PRIVATE PVFRD_BUILDING PUBLIC PVFRD_SHARED)
else()
  add_library(pvfrd STATIC ${PVFRD_SOURCES})
endif()

target_include_directories(pvfrd
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party)

# Floating-point contraction off, on every compiler.
#
# Load-bearing, not tidiness. The conformance suite asserts that the derived
# von Mises arrays are bit-identical to the reference implementation's NumPy
# expression. With contraction enabled the compiler is free to fuse a multiply
# and an add into one FMA, which is more accurate and therefore *different* --
# and the difference shows up only on hardware that has the instruction, so a
# build that passed on one runner would fail on another for reasons no one
# would look for. Turning it off makes the arithmetic mean what it says.
if(MSVC)
  target_compile_options(pvfrd PRIVATE /W4 /fp:precise)
else()
  target_compile_options(pvfrd PRIVATE -Wall -Wextra -ffp-contract=off)
endif()

# An FRD file can be larger than 2 GiB; the parser indexes it by byte offset.
if(NOT MSVC)
  target_compile_definitions(pvfrd PRIVATE _FILE_OFFSET_BITS=64)
endif()

if(PVFRD_BUILD_TOOLS)
  add_executable(frd_dump tools/frd_dump.cpp)
  target_link_libraries(frd_dump PRIVATE pvfrd)
  target_include_directories(frd_dump PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
endif()

if(PVFRD_BUILD_TESTS)
  include(CTest)
  enable_testing()

  find_package(GTest QUIET)
  if(NOT GTest_FOUND)
    include(FetchContent)
    # Pinned by hash, not by tag: a tag can be moved.
    FetchContent_Declare(googletest
      URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
      URL_HASH SHA256=7b42b4d6ed48810c5362c265a17faebe90dc2373c885e5216439d37927f02926)
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
  endif()

  # The tests reach into src/ headers, so they compile the sources directly
  # rather than linking the shared library: text.h and the derived-quantity
  # helpers are not part of the C ABI and are deliberately not exported.
  add_executable(pvfrd_tests
    tests/test_text.cpp
    tests/test_derived.cpp
    tests/test_parse.cpp
    tests/test_api.cpp
    tests/test_exceptions.cpp
    ${PVFRD_SOURCES})
  target_include_directories(pvfrd_tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
  target_link_libraries(pvfrd_tests PRIVATE GTest::gtest GTest::gtest_main)
  if(MSVC)
    target_compile_options(pvfrd_tests PRIVATE /fp:precise)
  else()
    target_compile_options(pvfrd_tests PRIVATE -ffp-contract=off)
  endif()
  target_compile_definitions(pvfrd_tests PRIVATE
    PVFRD_FIXTURE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures")

  # The fuzz entry point, driven over the committed corpus without libFuzzer.
  # This is what keeps the checks inside fuzz_parse.cpp from being code that
  # only ever runs in the one job that has Clang -- and it puts them under the
  # sanitizer lane, where they can report rather than merely crash.
  add_executable(fuzz_replay tests/fuzz_replay.cpp tests/fuzz_parse.cpp ${PVFRD_SOURCES})
  target_include_directories(fuzz_replay PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party)

  file(GLOB PVFRD_CORPUS
    "${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures/*.frd"
    "${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures/elements/*.frd")
  list(LENGTH PVFRD_CORPUS PVFRD_CORPUS_SIZE)
  if(PVFRD_CORPUS_SIZE LESS 30)
    # A replay over an empty or shrunken corpus passes. Configuring is where
    # that can still be said out loud.
    message(FATAL_ERROR
      "pvfrd: found only ${PVFRD_CORPUS_SIZE} fixtures; the corpus has shrunk")
  endif()
  message(STATUS "pvfrd: replaying the fuzz target over ${PVFRD_CORPUS_SIZE} fixtures")

  include(GoogleTest)
  # One CTest entry per test binary, not per test case: discovery mode runs
  # the binary at build time to enumerate, which costs a process per case and
  # defeats the build cache for no benefit at this suite's size.
  add_test(NAME pvfrd_tests COMMAND pvfrd_tests)
  add_test(NAME pvfrd_fuzz_replay COMMAND fuzz_replay ${PVFRD_CORPUS})
endif()

if(PVFRD_BUILD_FUZZERS)
  add_executable(fuzz_parse tests/fuzz_parse.cpp ${PVFRD_SOURCES})
  target_include_directories(fuzz_parse PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
  target_compile_options(fuzz_parse PRIVATE -fsanitize=fuzzer,address,undefined -ffp-contract=off)
  target_link_options(fuzz_parse PRIVATE -fsanitize=fuzzer,address,undefined)
endif()

include(GNUInstallDirs)
install(TARGETS pvfrd
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
