#include "oih_vector_similarity.h"

#include <float.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


#define REQUIRE(expression) \
    do { \
        if (!(expression)) { \
            (void)fprintf(stderr, "requirement failed at %s:%d: %s\n", __FILE__, __LINE__, #expression); \
            exit(EXIT_FAILURE); \
        } \
    } while (0)


static int close_enough(float actual, float expected) {
    return fabsf(actual - expected) <= 1.0e-6F;
}


static void test_happy_path(void) {
    const float left[] = {1.0F, 0.0F, 1.0F};
    const float right[] = {1.0F, 1.0F, 0.0F};
    const float rows[] = {
        1.0F, 0.0F, 1.0F,
        1.0F, 1.0F, 0.0F
    };
    float output = 0.0F;
    float batch_output[2] = {0.0F, 0.0F};

    REQUIRE(oih_vector_abi_version() == OIH_VECTOR_ABI_VERSION);
    REQUIRE(strstr(oih_vector_build_info(), "abi=1;implementation=scalar") != NULL);
    REQUIRE(oih_dot_f32(left, right, 3U, &output) == OIH_VECTOR_OK);
    REQUIRE(close_enough(output, 1.0F));
    REQUIRE(oih_l2_norm_f32(left, 3U, &output) == OIH_VECTOR_OK);
    REQUIRE(close_enough(output, sqrtf(2.0F)));
    REQUIRE(oih_cosine_similarity_f32(left, right, 3U, &output) == OIH_VECTOR_OK);
    REQUIRE(close_enough(output, 0.5F));
    REQUIRE(oih_cosine_batch_f32(left, rows, 2U, 3U, batch_output) == OIH_VECTOR_OK);
    REQUIRE(close_enough(batch_output[0], 1.0F));
    REQUIRE(close_enough(batch_output[1], 0.5F));
}


static void test_errors(void) {
    const float values[] = {1.0F, 2.0F};
    const float zero[] = {0.0F, 0.0F};
    const float non_finite[] = {NAN, 1.0F};
    const float infinite[] = {INFINITY, 1.0F};
    const float extreme[] = {FLT_MAX, FLT_MAX};
    float output = 0.0F;

    REQUIRE(oih_dot_f32(NULL, values, 2U, &output) == OIH_VECTOR_NULL_POINTER);
    REQUIRE(oih_dot_f32(values, values, 0U, &output) == OIH_VECTOR_ZERO_LENGTH);
    REQUIRE(oih_cosine_similarity_f32(values, zero, 2U, &output) == OIH_VECTOR_ZERO_NORM);
    REQUIRE(
        oih_cosine_similarity_f32(values, non_finite, 2U, &output)
        == OIH_VECTOR_NON_FINITE
    );
    REQUIRE(oih_l2_norm_f32(infinite, 2U, &output) == OIH_VECTOR_NON_FINITE);
    REQUIRE(oih_dot_f32(extreme, extreme, 2U, &output) == OIH_VECTOR_NON_FINITE);
    REQUIRE(
        oih_cosine_batch_f32(values, values, SIZE_MAX, 2U, &output)
        == OIH_VECTOR_SIZE_OVERFLOW
    );
}


int main(void) {
    test_happy_path();
    test_errors();
    return 0;
}
