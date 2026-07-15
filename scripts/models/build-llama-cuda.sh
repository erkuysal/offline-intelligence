#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ENV="offline-ai-llama-build"
EXPECTED_COMMIT="c198af4dc24f8e0ab8a569a60f931e03a192fd79"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-${HOME}/tools/llama.cpp}"
BUILD_DIR="${LLAMA_CUDA_BUILD_DIR:-${LLAMA_CPP_DIR}/build-cuda}"
JOBS="${LLAMA_BUILD_JOBS:-8}"
CUDA_ARCHITECTURES="${LLAMA_CUDA_ARCHITECTURES:-120a-real}"
TOOLKIT_VIEW="${LLAMA_CUDA_TOOLKIT_VIEW:-var/build/llama-cuda-13.0-toolkit}"

if [[ "${TOOLKIT_VIEW}" != /* ]]; then
  TOOLKIT_VIEW="${PWD}/${TOOLKIT_VIEW}"
fi

if [[ "${CONDA_DEFAULT_ENV:-}" != "${EXPECTED_ENV}" ]]; then
  echo "Run this script through: conda run -n ${EXPECTED_ENV} bash $0 [--clean]" >&2
  exit 2
fi

if [[ ! -d "${LLAMA_CPP_DIR}/.git" ]]; then
  echo "llama.cpp checkout not found at ${LLAMA_CPP_DIR}" >&2
  exit 2
fi

actual_commit="$(git -C "${LLAMA_CPP_DIR}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${EXPECTED_COMMIT}" ]]; then
  echo "Expected llama.cpp ${EXPECTED_COMMIT}; found ${actual_commit}" >&2
  exit 2
fi

if [[ "${1:-}" == "--clean" ]]; then
  cmake -E remove_directory "${BUILD_DIR}"
elif [[ -n "${1:-}" ]]; then
  echo "Unknown argument: ${1}" >&2
  exit 2
fi

python_site="${CONDA_PREFIX}/lib/python3.12/site-packages"
cuda_root="${python_site}/nvidia/cu13"
cuda_lib="${cuda_root}/lib"
cuda_nvcc="${cuda_root}/bin/nvcc"
host_c="${CONDA_PREFIX}/bin/x86_64-conda-linux-gnu-cc"
host_cxx="${CONDA_PREFIX}/bin/x86_64-conda-linux-gnu-c++"

for required_path in \
  "${cuda_nvcc}" \
  "${cuda_root}/include" \
  "${cuda_root}/nvvm" \
  "${cuda_lib}/libcudart.so.13" \
  "${cuda_lib}/libcublas.so.13" \
  "${cuda_lib}/libcublasLt.so.13" \
  "${host_c}" \
  "${host_cxx}" \
  "/usr/lib/wsl/lib/libcuda.so.1"; do
  if [[ ! -e "${required_path}" ]]; then
    echo "Required build input is missing: ${required_path}" >&2
    exit 2
  fi
done

cmake -E remove_directory "${TOOLKIT_VIEW}"
cmake -E make_directory "${TOOLKIT_VIEW}"
cmake -E create_symlink "${cuda_root}/bin" "${TOOLKIT_VIEW}/bin"
cmake -E create_symlink "${cuda_root}/include" "${TOOLKIT_VIEW}/include"
cmake -E create_symlink "${cuda_root}/nvvm" "${TOOLKIT_VIEW}/nvvm"
cmake -E make_directory "${TOOLKIT_VIEW}/lib64"
for library in "${cuda_lib}"/*; do
  cmake -E create_symlink "${library}" "${TOOLKIT_VIEW}/lib64/$(basename "${library}")"
done
cmake -E create_symlink "${cuda_lib}/libcudart.so.13" "${TOOLKIT_VIEW}/lib64/libcudart.so"
cmake -E create_symlink "${cuda_lib}/libcublas.so.13" "${TOOLKIT_VIEW}/lib64/libcublas.so"
cmake -E create_symlink "${cuda_lib}/libcublasLt.so.13" "${TOOLKIT_VIEW}/lib64/libcublasLt.so"

link_paths="-L${cuda_lib} -L${CONDA_PREFIX}/lib -L/usr/lib/wsl/lib"
rpath_links="-Wl,-rpath-link,${cuda_lib} -Wl,-rpath-link,${CONDA_PREFIX}/lib -Wl,-rpath-link,/usr/lib/wsl/lib"
build_rpath="${cuda_lib};${CONDA_PREFIX}/lib;/usr/lib/wsl/lib"

cmake \
  -S "${LLAMA_CPP_DIR}" \
  -B "${BUILD_DIR}" \
  -DGGML_CUDA=ON \
  -DGGML_NATIVE=OFF \
  -DGGML_CUDA_F16=ON \
  -DGGML_CCACHE=OFF \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="${host_c}" \
  -DCMAKE_CXX_COMPILER="${host_cxx}" \
  -DCMAKE_CUDA_COMPILER="${TOOLKIT_VIEW}/bin/nvcc" \
  -DCMAKE_CUDA_HOST_COMPILER="${host_cxx}" \
  -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES}" \
  -DCUDAToolkit_ROOT="${TOOLKIT_VIEW}" \
  -DCMAKE_CUDA_FLAGS="-L${cuda_lib}" \
  -DCMAKE_EXE_LINKER_FLAGS="${link_paths} ${rpath_links}" \
  -DCMAKE_SHARED_LINKER_FLAGS="${link_paths} ${rpath_links}" \
  -DCMAKE_BUILD_RPATH="${build_rpath}" \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON

cmake --build "${BUILD_DIR}" --target llama-server --parallel "${JOBS}"

echo "Built ${BUILD_DIR}/bin/llama-server"
