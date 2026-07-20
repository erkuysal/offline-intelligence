#ifndef OIH_VECTOR_SIMILARITY_H
#define OIH_VECTOR_SIMILARITY_H

#include <stddef.h>

#if defined(_WIN32) && defined(OIH_VECTOR_SIMILARITY_BUILD)
#define OIH_VECTOR_API __declspec(dllexport)
#elif defined(_WIN32)
#define OIH_VECTOR_API __declspec(dllimport)
#else
#define OIH_VECTOR_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define OIH_VECTOR_ABI_VERSION 1

typedef enum oih_vector_status {
    OIH_VECTOR_OK = 0,
    OIH_VECTOR_NULL_POINTER = 1,
    OIH_VECTOR_ZERO_LENGTH = 2,
    OIH_VECTOR_SIZE_OVERFLOW = 3,
    OIH_VECTOR_ZERO_NORM = 4,
    OIH_VECTOR_NON_FINITE = 5
} oih_vector_status;

OIH_VECTOR_API int oih_vector_abi_version(void);
OIH_VECTOR_API const char *oih_vector_build_info(void);

OIH_VECTOR_API oih_vector_status oih_dot_f32(
    const float *left,
    const float *right,
    size_t length,
    float *output
);

OIH_VECTOR_API oih_vector_status oih_l2_norm_f32(
    const float *values,
    size_t length,
    float *output
);

OIH_VECTOR_API oih_vector_status oih_cosine_similarity_f32(
    const float *left,
    const float *right,
    size_t length,
    float *output
);

OIH_VECTOR_API oih_vector_status oih_cosine_batch_f32(
    const float *query,
    const float *rows,
    size_t row_count,
    size_t dimensions,
    float *output
);

#ifdef __cplusplus
}
#endif

#endif
