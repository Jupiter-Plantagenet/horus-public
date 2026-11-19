
# HORUS finals: E2SM-RC Style 2 / Action 6 (slice-level PRB quota) control xApp
add_executable(xapp_horus_rc
        xapp_horus_rc.c
        ${CMAKE_SOURCE_DIR}/src/util/alg_ds/alg/defer.c
        )

target_link_libraries(xapp_horus_rc
        PUBLIC
        e42_xapp
        $<TARGET_OBJECTS:e2_time_obj>
        -pthread
        -lsctp
        -ldl
        )
