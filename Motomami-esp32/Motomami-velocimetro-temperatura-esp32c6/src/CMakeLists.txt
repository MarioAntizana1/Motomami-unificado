FILE(GLOB_RECURSE app_sources ${CMAKE_SOURCE_DIR}/src/*.*)
idf_component_register(SRCS ${app_sources} REQUIRES esp_mqtt esp_http_server app_update esp_timer)
