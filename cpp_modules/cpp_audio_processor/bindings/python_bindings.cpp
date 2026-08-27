#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include "audio_vad.h"
#include <algorithm>

namespace py = pybind11;

PYBIND11_MODULE(audio_processor_py, m) {
    m.doc() = "C++ Audio Preprocessing and VAD for Xiaoyou Core";

    py::class_<xiaoyou::audio::AudioVAD>(m, "AudioVAD")
        .def(py::init<int, float>(), 
             py::arg("sample_rate") = 16000, 
             py::arg("energy_threshold") = 0.05,
             "Initialize the Energy-based VAD")
             
        .def("is_speech", [](xiaoyou::audio::AudioVAD& self, py::array_t<int16_t> array) {
            py::buffer_info buf = array.request();
            if (buf.ndim != 1) {
                throw std::runtime_error("Audio data must be a 1D array");
            }
            return self.is_speech(static_cast<const int16_t*>(buf.ptr), buf.shape[0]);
        }, py::arg("audio_data"), "Check if a 1D numpy array of audio contains speech")
        
        .def("remove_silence", [](xiaoyou::audio::AudioVAD& self, py::array_t<int16_t> array, int frame_ms) {
            py::buffer_info buf = array.request();
            if (buf.ndim != 1) {
                throw std::runtime_error("Audio data must be a 1D array");
            }
            
            // Execute C++ logic
            auto result_vec = self.remove_silence(static_cast<const int16_t*>(buf.ptr), buf.shape[0], frame_ms);
            
            // Convert C++ vector back to zero-copy numpy array for Python
            auto result_array = py::array_t<int16_t>(result_vec.size());
            py::buffer_info res_buf = result_array.request();
            int16_t* ptr = static_cast<int16_t*>(res_buf.ptr);
            std::copy(result_vec.begin(), result_vec.end(), ptr);
            
            return result_array;
        }, py::arg("audio_data"), py::arg("frame_ms") = 30, "Remove silence frames and return a clean numpy array");
}
