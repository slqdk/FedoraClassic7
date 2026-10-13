# Classic 7 taskbar right-click menu: a Plasma "containment actions" plugin, so the menu you get
# when right-clicking the taskbar has Windows 7's entries (Start Task Manager, Show the desktop,
# Cascade windows...). Built against the image's own libplasma during the image build.
cmake_minimum_required(VERSION 3.16)
project(classic7-taskbarmenu LANGUAGES CXX)
find_package(ECM REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets DBus)
find_package(KF6 REQUIRED COMPONENTS CoreAddons)
find_package(Plasma REQUIRED)
kcoreaddons_add_plugin(classic7_taskbarmenu SOURCES taskbarmenu.cpp INSTALL_NAMESPACE "plasma/containmentactions")
set_target_properties(classic7_taskbarmenu PROPERTIES OUTPUT_NAME org.classic7.taskbarmenu)
target_link_libraries(classic7_taskbarmenu Qt6::Gui Qt6::Widgets Qt6::DBus KF6::CoreAddons Plasma::Plasma)
