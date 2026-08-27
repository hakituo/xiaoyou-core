#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "bpe_tokenizer.h"

namespace py = pybind11;

PYBIND11_MODULE(fast_tokenizer_py, m) {
    m.doc() = "Ultra-fast C++ Token Counter & Truncator for Xiaoyou Core Context Window Management";

    py::class_<xiaoyou::tokenizer::FastBPETokenizer>(m, "FastTokenizer")
        .def(py::init<>())
        .def("count_tokens", &xiaoyou::tokenizer::FastBPETokenizer::count_tokens, 
             py::arg("text"),
             "Quickly approximate the number of LLM tokens in a string without heavy model loading")
        .def("truncate_from_back", &xiaoyou::tokenizer::FastBPETokenizer::truncate_from_back,
             py::arg("text"), py::arg("max_tokens"),
             "Safely truncate text from the front to ensure it fits in the max_tokens context window");
}
