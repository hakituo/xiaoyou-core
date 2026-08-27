#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "bert_engine.h"

namespace py = pybind11;

PYBIND11_MODULE(bert_engine_py, m) {
    m.doc() = "C++ implementation of BERT inference with ONNX Runtime for Xiaoyou Core";

    py::class_<xiaoyou::bert::BertEngine>(m, "BertPredictor")
        .def(py::init<const std::string&, const std::string&>(), 
             py::arg("model_path"), py::arg("vocab_path"))
        .def("predict", &xiaoyou::bert::BertEngine::predict, 
             py::arg("text"),
             "Predict intent logits from text");
}
