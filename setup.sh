#!/bin/bash
# Build CTranslate2 from source for DGX Spark / GB10 (sm_121), then install
# Python deps. Mirrors Dockerfile stages 2-3 for host (non-Docker) use.
set -euo pipefail

export CUDAARCHS=121

REPO_DIR="$(pwd)"
mkdir -p build && cd build

# 1. Build CTranslate2 with CUDA support for Blackwell
echo "Cloning CTranslate2 to setup GPU-enabled ASR"
[ -d CTranslate2 ] || git clone --recursive https://github.com/OpenNMT/CTranslate2.git
cd CTranslate2

# Patch: CMake doesn't know Blackwell, so comment out cuda_select_nvcc_arch_flags
# and hard-code the gencode flag for sm_121.
sed -i 's/cuda_select_nvcc_arch_flags/#cuda_select_nvcc_arch_flags/' CMakeLists.txt
sed -i 's/list(APPEND CUDA_NVCC_FLAGS ${CUDA_NVCC_FLAGS_READABLE})/list(APPEND CUDA_NVCC_FLAGS "-gencode=arch=compute_121,code=sm_121")/' CMakeLists.txt

mkdir -p build && cd build
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DWITH_CUDA=ON \
    -DWITH_CUDNN=OFF \
    -DWITH_MKL=OFF \
    -DOPENMP_RUNTIME=NONE \
    -DCMAKE_INSTALL_PREFIX=/usr/local
make -j"$(nproc)"
sudo make install
sudo ldconfig

# Install CTranslate2 Python bindings
pip install "$REPO_DIR/build/CTranslate2/python"

cd "$REPO_DIR"
pip install -r requirements.txt
