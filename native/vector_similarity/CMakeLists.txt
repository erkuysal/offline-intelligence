cmake_minimum_required(VERSION 3.20)
project(oih_vector_similarity VERSION 0.1.0 LANGUAGES C)

option(OIH_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)

add_library(oih_vector_similarity SHARED src/oih_vector_similarity.c)
target_include_directories(
    oih_vector_similarity
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_compile_definitions(oih_vector_similarity PRIVATE OIH_VECTOR_SIMILARITY_BUILD)
target_compile_features(oih_vector_similarity PUBLIC c_std_11)

if(MSVC)
    target_compile_options(oih_vector_similarity PRIVATE /W4 /WX)
else()
    target_compile_options(oih_vector_similarity PRIVATE -Wall -Wextra -Wpedantic -Werror)
    target_link_libraries(oih_vector_similarity PRIVATE m)
endif()

if(OIH_ENABLE_SANITIZERS AND NOT MSVC)
    target_compile_options(oih_vector_similarity PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(oih_vector_similarity PRIVATE -fsanitize=address,undefined)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(oih_vector_similarity_test tests/test_vector_similarity.c)
    target_link_libraries(oih_vector_similarity_test PRIVATE oih_vector_similarity)
    target_compile_features(oih_vector_similarity_test PRIVATE c_std_11)
    if(MSVC)
        target_compile_options(oih_vector_similarity_test PRIVATE /W4 /WX)
    else()
        target_compile_options(oih_vector_similarity_test PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    if(OIH_ENABLE_SANITIZERS AND NOT MSVC)
        target_compile_options(oih_vector_similarity_test PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(oih_vector_similarity_test PRIVATE -fsanitize=address,undefined)
    endif()
    add_test(NAME oih_vector_similarity_test COMMAND oih_vector_similarity_test)
    if(OIH_ENABLE_SANITIZERS AND NOT MSVC)
        set_tests_properties(
            oih_vector_similarity_test
            PROPERTIES ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0"
        )
    endif()
endif()

install(
    TARGETS oih_vector_similarity
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin
    ARCHIVE DESTINATION lib
)
install(FILES include/oih_vector_similarity.h DESTINATION include)
