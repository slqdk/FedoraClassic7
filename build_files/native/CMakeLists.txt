# Classic 7's small native parts, built against the image's own KDE libraries during the image build:
#   org.classic7.taskbarmenu  Plasma "containment actions" plugin: the taskbar's Windows 7 right-click menu
#   classic7-grab             takes the screen picture for Quick Shot (KWin allows ScreenShot2 only to
#                             programs whose desktop file asks for it, matched by executable path)
#   classic7-idle             tells the screensaver when the user has been idle (KIdleTime)
cmake_minimum_required(VERSION 3.16)
project(classic7-native LANGUAGES CXX)
find_package(ECM REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets DBus)
find_package(KF6 REQUIRED COMPONENTS CoreAddons Config Package WindowSystem IdleTime)
find_package(Plasma REQUIRED)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

kcoreaddons_add_plugin(classic7_taskbarmenu SOURCES taskbarmenu.cpp INSTALL_NAMESPACE "plasma/containmentactions")
set_target_properties(classic7_taskbarmenu PROPERTIES OUTPUT_NAME org.classic7.taskbarmenu)
target_link_libraries(classic7_taskbarmenu Qt6::Gui Qt6::Widgets Qt6::DBus KF6::CoreAddons Plasma::Plasma)

add_executable(classic7-grab grab.cpp)
target_link_libraries(classic7-grab Qt6::Core Qt6::DBus)
install(TARGETS classic7-grab DESTINATION ${KDE_INSTALL_LIBEXECDIR})

add_executable(classic7-idle idle.cpp)
target_link_libraries(classic7-idle Qt6::Gui KF6::IdleTime)
install(TARGETS classic7-idle DESTINATION ${KDE_INSTALL_LIBEXECDIR})
