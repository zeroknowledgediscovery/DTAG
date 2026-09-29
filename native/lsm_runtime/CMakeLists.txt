cmake_minimum_required(VERSION 3.18)
project(dtag_lsm_runtime LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

find_package(Threads REQUIRED)
include(FetchContent)

FetchContent_Declare(
  nlohmann_json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.11.3
)
FetchContent_MakeAvailable(nlohmann_json)

FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG v2.12.0
)
FetchContent_MakeAvailable(pybind11)

pybind11_add_module(
  dtag_lsm
  bindings/dtag_lsm_runtime.cpp
  src/SourceMaps/SourceMapStore.cpp
  src/PredictDistribution/PredictDistribution.cpp
  src/QDistance/qdistance.cpp
  src/Tree/Tree.cpp
)

target_include_directories(dtag_lsm PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(
  dtag_lsm
  PRIVATE
  nlohmann_json::nlohmann_json
  Threads::Threads
)

# Do not statically link libstdc++/libgcc into a pybind11 extension.
# DTAG's LSM runtime code itself is compiled directly into dtag_lsm.so; the
# host compiler runtimes remain dynamic to preserve the CPython/C++ ABI.
set_target_properties(
  dtag_lsm
  PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/python"
)
