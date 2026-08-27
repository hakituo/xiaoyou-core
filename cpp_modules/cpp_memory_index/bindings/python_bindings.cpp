#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "../core/vector_indexer.h"
#include <omp.h>
#include <atomic>

namespace py = pybind11;
using namespace ai_memory;

static std::atomic<int> g_concurrent_searches{0};

PYBIND11_MODULE(memory_index_py, m) {
    m.doc() = "AI Memory Vector Indexer Python Bindings";

    py::class_<SearchResult>(m, "SearchResult")
        .def_readwrite("id", &SearchResult::id)
        .def_readwrite("similarity", &SearchResult::similarity)
        .def_readwrite("final_score", &SearchResult::final_score);

    py::class_<VectorIndexer, std::shared_ptr<VectorIndexer>>(m, "VectorIndexer")
        .def(py::init<>())
        .def("addRecord", &VectorIndexer::addRecord,
             py::arg("id"), py::arg("embedding"), py::arg("weight"),
             py::arg("timestamp"), py::arg("source"), py::arg("topics"),
             py::call_guard<py::gil_scoped_release>())
        .def("removeRecord", &VectorIndexer::removeRecord, py::arg("id"),
             py::call_guard<py::gil_scoped_release>())
        .def("clear", &VectorIndexer::clear,
             py::call_guard<py::gil_scoped_release>())
        .def("search", [](VectorIndexer& self,
                          const std::vector<float>& query_embedding,
                          int top_k, float min_similarity,
                          float current_time, float decay_rate,
                          float base_min_weight, float absolute_min_weight,
                          const std::string& filter_source,
                          const std::vector<std::string>& filter_topics) {
            int concurrent = g_concurrent_searches.fetch_add(1) + 1;
            int total_cores = omp_get_num_procs();
            int threads_for_this = std::max(1, total_cores / concurrent);

            {
                py::gil_scoped_release release;
                omp_set_num_threads(threads_for_this);
                auto result = self.search(query_embedding, top_k, min_similarity,
                                         current_time, decay_rate,
                                         base_min_weight, absolute_min_weight,
                                         filter_source, filter_topics);
                g_concurrent_searches.fetch_sub(1);
                omp_set_num_threads(total_cores);
                py::gil_scoped_acquire acquire;
                return result;
            }
        }, py::arg("query_embedding"), py::arg("top_k"), py::arg("min_similarity"),
           py::arg("current_time"), py::arg("decay_rate"), py::arg("base_min_weight"),
           py::arg("absolute_min_weight"), py::arg("filter_source") = "",
           py::arg("filter_topics") = std::vector<std::string>())
        .def_static("setOpenMPThreads", [](int n) {
            omp_set_num_threads(n);
        }, py::arg("n"))
        .def_static("getOpenMPThreads", []() {
            return omp_get_max_threads();
        })
        .def_static("getNumProcs", []() {
            return omp_get_num_procs();
        });
}
