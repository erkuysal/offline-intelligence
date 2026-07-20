#include "oih_vector_similarity.h"

#include <float.h>
#include <math.h>
#include <stdint.h>

#define OIH_STRINGIFY_INNER(value) #value
#define OIH_STRINGIFY(value) OIH_STRINGIFY_INNER(value)

#if defined(__clang__)
#define OIH_COMPILER_INFO "clang-" __clang_version__
#elif defined(__GNUC__)
#define OIH_COMPILER_INFO "gcc-" OIH_STRINGIFY(__GNUC__) "." OIH_STRINGIFY(__GNUC_MINOR__)
#elif defined(_MSC_VER)
#define OIH_COMPILER_INFO "msvc-" OIH_STRINGIFY(_MSC_VER)
#else
#define OIH_COMPILER_INFO "unknown-compiler"
#endif

static oih_vector_status validate_vector_arguments(
    const float *left,
    const float *right,
    size_t length,
    const float *output
) {
    if (left == NULL || right == NULL || output == NULL) {
        return OIH_VECTOR_NULL_POINTER;
    }
    if (length == 0U) {
        return OIH_VECTOR_ZERO_LENGTH;
    }
    return OIH_VECTOR_OK;
}


static oih_vector_status accumulate_dot_and_norms(
    const float *left,
    const float *right,
    size_t length,
    double *dot,
    double *left_norm_squared,
    double *right_norm_squared
) {
    size_t index;
    double dot_sum = 0.0;
    double left_sum = 0.0;
    double right_sum = 0.0;

    for (index = 0U; index < length; ++index) {
        const double left_value = (double)left[index];
        const double right_value = (double)right[index];
        if (!isfinite(left_value) || !isfinite(right_value)) {
            return OIH_VECTOR_NON_FINITE;
        }
        dot_sum += left_value * right_value;
        left_sum += left_value * left_value;
        right_sum += right_value * right_value;
    }
    if (!isfinite(dot_sum) || !isfinite(left_sum) || !isfinite(right_sum)) {
        return OIH_VECTOR_NON_FINITE;
    }
    *dot = dot_sum;
    *left_norm_squared = left_sum;
    *right_norm_squared = right_sum;
    return OIH_VECTOR_OK;
}


int oih_vector_abi_version(void) {
    return OIH_VECTOR_ABI_VERSION;
}


const char *oih_vector_build_info(void) {
    return "abi=1;implementation=scalar;c_standard=11;compiler=" OIH_COMPILER_INFO;
}


oih_vector_status oih_dot_f32(
    const float *left,
    const float *right,
    size_t length,
    float *output
) {
    size_t index;
    double sum = 0.0;
    oih_vector_status status = validate_vector_arguments(left, right, length, output);
    if (status != OIH_VECTOR_OK) {
        return status;
    }
    for (index = 0U; index < length; ++index) {
        const double left_value = (double)left[index];
        const double right_value = (double)right[index];
        if (!isfinite(left_value) || !isfinite(right_value)) {
            return OIH_VECTOR_NON_FINITE;
        }
        sum += left_value * right_value;
    }
    if (!isfinite(sum) || sum > (double)FLT_MAX || sum < -(double)FLT_MAX) {
        return OIH_VECTOR_NON_FINITE;
    }
    *output = (float)sum;
    return OIH_VECTOR_OK;
}


oih_vector_status oih_l2_norm_f32(
    const float *values,
    size_t length,
    float *output
) {
    size_t index;
    double sum = 0.0;
    if (values == NULL || output == NULL) {
        return OIH_VECTOR_NULL_POINTER;
    }
    if (length == 0U) {
        return OIH_VECTOR_ZERO_LENGTH;
    }
    for (index = 0U; index < length; ++index) {
        const double value = (double)values[index];
        if (!isfinite(value)) {
            return OIH_VECTOR_NON_FINITE;
        }
        sum += value * value;
    }
    sum = sqrt(sum);
    if (!isfinite(sum) || sum > (double)FLT_MAX) {
        return OIH_VECTOR_NON_FINITE;
    }
    *output = (float)sum;
    return OIH_VECTOR_OK;
}


oih_vector_status oih_cosine_similarity_f32(
    const float *left,
    const float *right,
    size_t length,
    float *output
) {
    double dot;
    double left_norm_squared;
    double right_norm_squared;
    double denominator;
    double result;
    oih_vector_status status = validate_vector_arguments(left, right, length, output);
    if (status != OIH_VECTOR_OK) {
        return status;
    }
    status = accumulate_dot_and_norms(
        left,
        right,
        length,
        &dot,
        &left_norm_squared,
        &right_norm_squared
    );
    if (status != OIH_VECTOR_OK) {
        return status;
    }
    if (left_norm_squared == 0.0 || right_norm_squared == 0.0) {
        return OIH_VECTOR_ZERO_NORM;
    }
    denominator = sqrt(left_norm_squared) * sqrt(right_norm_squared);
    result = dot / denominator;
    if (!isfinite(result)) {
        return OIH_VECTOR_NON_FINITE;
    }
    *output = (float)result;
    return OIH_VECTOR_OK;
}


oih_vector_status oih_cosine_batch_f32(
    const float *query,
    const float *rows,
    size_t row_count,
    size_t dimensions,
    float *output
) {
    size_t dimension_index;
    size_t row_index;
    double query_norm;
    double query_norm_squared = 0.0;
    if (query == NULL || rows == NULL || output == NULL) {
        return OIH_VECTOR_NULL_POINTER;
    }
    if (row_count == 0U || dimensions == 0U) {
        return OIH_VECTOR_ZERO_LENGTH;
    }
    if (row_count > SIZE_MAX / dimensions) {
        return OIH_VECTOR_SIZE_OVERFLOW;
    }
    for (dimension_index = 0U; dimension_index < dimensions; ++dimension_index) {
        const double query_value = (double)query[dimension_index];
        if (!isfinite(query_value)) {
            return OIH_VECTOR_NON_FINITE;
        }
        query_norm_squared += query_value * query_value;
    }
    if (!isfinite(query_norm_squared)) {
        return OIH_VECTOR_NON_FINITE;
    }
    if (query_norm_squared == 0.0) {
        return OIH_VECTOR_ZERO_NORM;
    }
    query_norm = sqrt(query_norm_squared);
    for (row_index = 0U; row_index < row_count; ++row_index) {
        const size_t offset = row_index * dimensions;
        double dot = 0.0;
        double row_norm_squared = 0.0;
        double result;
        for (dimension_index = 0U; dimension_index < dimensions; ++dimension_index) {
            const double query_value = (double)query[dimension_index];
            const double row_value = (double)rows[offset + dimension_index];
            if (!isfinite(row_value)) {
                return OIH_VECTOR_NON_FINITE;
            }
            dot += query_value * row_value;
            row_norm_squared += row_value * row_value;
        }
        if (!isfinite(dot) || !isfinite(row_norm_squared)) {
            return OIH_VECTOR_NON_FINITE;
        }
        if (row_norm_squared == 0.0) {
            return OIH_VECTOR_ZERO_NORM;
        }
        result = dot / (query_norm * sqrt(row_norm_squared));
        if (!isfinite(result)) {
            return OIH_VECTOR_NON_FINITE;
        }
        output[row_index] = (float)result;
    }
    return OIH_VECTOR_OK;
}
