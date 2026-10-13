# A KIO copy with the normal progress reporting, for the CI test of the copy window
cmake_minimum_required(VERSION 3.16)
project(kiocopy LANGUAGES CXX)
find_package(Qt6 REQUIRED COMPONENTS Widgets)
find_package(KF6KIO REQUIRED)
add_executable(kiocopy kiocopy.cpp)
target_link_libraries(kiocopy Qt6::Widgets KF6::KIOCore KF6::KIOWidgets)
