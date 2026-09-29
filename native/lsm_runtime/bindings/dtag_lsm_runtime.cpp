#include "PredictDistribution/PredictDistribution.h"
#include "QDistance/qdistance.h"
#include "SourceMaps/SourceMaps.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <filesystem>
#include <future>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace fs = std::filesystem;
namespace py = pybind11;

namespace {

std::vector<std::string> row_to_tokens(const py::object& row) {
    py::sequence seq = py::reinterpret_borrow<py::sequence>(row);
    const ssize_t n = py::len(seq);
    std::vector<std::string> out;
    out.reserve(static_cast<size_t>(n));
    for (ssize_t i = 0; i < n; ++i) out.emplace_back(py::str(seq[i]));
    return out;
}

py::dict counts_to_prob_dict(
    sourcemaps::SourceMapStore& store,
    int target_col_id,
    const std::map<int, int>& counts
) {
    long long total = 0;
    for (const auto& kv : counts) total += kv.second;

    py::dict out;
    if (total <= 0) return out;

    if (!store.tryGet(target_col_id)) {
        for (const auto& kv : counts) {
            out[py::cast(kv.first)] =
                static_cast<double>(kv.second) / static_cast<double>(total);
        }
        return out;
    }

    std::map<std::string, long long> labeled;
    for (const auto& kv : counts) {
        labeled[store.decodeLabel(target_col_id, kv.first)] += kv.second;
    }
    for (const auto& kv : labeled) {
        out[py::str(kv.first)] =
            static_cast<double>(kv.second) / static_cast<double>(total);
    }
    return out;
}

}  // namespace

class DTAGRuntime {
public:
    DTAGRuntime(
        const std::string& trees_dir,
        const std::string& run_dir,
        int cols_per_shard,
        std::vector<int> tree_ids,
        int n_columns,
        bool preload_trees = true,
        bool preload_source_maps = true
    )
        : trees_dir_(fs::absolute(trees_dir)),
          run_dir_(run_dir.empty()
                       ? sourcemaps::SourceMapStore::inferRunDir(trees_dir_)
                       : fs::absolute(run_dir)),
          cols_per_shard_(cols_per_shard),
          tree_ids_(std::move(tree_ids)),
          store_(run_dir_, cols_per_shard_),
          predictor_(trees_dir_.string()) {
        if (run_dir_.empty() || !fs::exists(run_dir_ / "source_maps")) {
            throw std::runtime_error("DTAGRuntime: run_dir must contain source_maps/");
        }
        if (tree_ids_.empty()) {
            throw std::invalid_argument("DTAGRuntime: tree_ids must be non-empty");
        }

        if (preload_source_maps && n_columns > 0) {
            std::vector<std::string> blank(static_cast<size_t>(n_columns), "");
            (void)store_.encodeRow(blank);
        }

        if (preload_trees) {
            py::gil_scoped_release release;
            predictor_.preload(tree_ids_);
        }
    }

    py::dict predict_distributions(
        const py::object& row,
        std::vector<int> target_tree_ids
    ) {
        if (target_tree_ids.empty()) target_tree_ids = tree_ids_;
        const auto tokens = row_to_tokens(row);
        const auto codes = store_.encodeRow(tokens);

        std::vector<std::pair<int, std::map<int, int>>> results;
        results.reserve(target_tree_ids.size());
        {
            py::gil_scoped_release release;
            for (int tid : target_tree_ids) {
                results.emplace_back(tid, predictor_.predict(tid, codes));
            }
        }

        py::dict out;
        for (const auto& item : results) {
            out[py::int_(item.first)] =
                counts_to_prob_dict(store_, item.first, item.second);
        }
        return out;
    }

    double qdistance(
        const py::object& row_a,
        const py::object& row_b,
        std::vector<int> tree_ids
    ) {
        if (tree_ids.empty()) tree_ids = tree_ids_;
        const auto a_codes = store_.encodeRow(row_to_tokens(row_a));
        const auto b_codes = store_.encodeRow(row_to_tokens(row_b));

        py::gil_scoped_release release;
        return ::qdistance(predictor_, a_codes, b_codes, tree_ids);
    }

    py::tuple distances_to_state(
        const py::object& left,
        const py::object& right,
        const py::object& state,
        std::vector<int> tree_ids
    ) {
        if (tree_ids.empty()) tree_ids = tree_ids_;
        const auto left_codes = store_.encodeRow(row_to_tokens(left));
        const auto right_codes = store_.encodeRow(row_to_tokens(right));
        const auto state_codes = store_.encodeRow(row_to_tokens(state));

        double d_left = 0.0;
        double d_right = 0.0;
        {
            py::gil_scoped_release release;
            auto f_left = std::async(std::launch::async, [&]() {
                return ::qdistance(predictor_, left_codes, state_codes, tree_ids);
            });
            auto f_right = std::async(std::launch::async, [&]() {
                return ::qdistance(predictor_, right_codes, state_codes, tree_ids);
            });
            d_left = f_left.get();
            d_right = f_right.get();
        }

        return py::make_tuple(d_left, d_right);
    }

    void preload() {
        py::gil_scoped_release release;
        predictor_.preload(tree_ids_);
    }

    size_t tree_count() const { return tree_ids_.size(); }
    std::string trees_dir() const { return trees_dir_.string(); }
    std::string run_dir() const { return run_dir_.string(); }

private:
    fs::path trees_dir_;
    fs::path run_dir_;
    int cols_per_shard_;
    std::vector<int> tree_ids_;
    sourcemaps::SourceMapStore store_;
    PredictDistribution predictor_;
};

PYBIND11_MODULE(dtag_lsm, m) {
    m.doc() = "Persistent native LSM runtime for Digital Twin Anchored Generation";

    py::class_<DTAGRuntime>(m, "Runtime")
        .def(
            py::init<
                const std::string&,
                const std::string&,
                int,
                std::vector<int>,
                int,
                bool,
                bool
            >(),
            py::arg("trees_dir"),
            py::arg("run_dir"),
            py::arg("cols_per_shard") = 50000,
            py::arg("tree_ids") = std::vector<int>{},
            py::arg("n_columns") = 0,
            py::arg("preload_trees") = true,
            py::arg("preload_source_maps") = true
        )
        .def(
            "predict_distributions",
            &DTAGRuntime::predict_distributions,
            py::arg("row"),
            py::arg("tree_ids") = std::vector<int>{}
        )
        .def(
            "qdistance",
            &DTAGRuntime::qdistance,
            py::arg("row_a"),
            py::arg("row_b"),
            py::arg("tree_ids") = std::vector<int>{}
        )
        .def(
            "distances_to_state",
            &DTAGRuntime::distances_to_state,
            py::arg("left"),
            py::arg("right"),
            py::arg("state"),
            py::arg("tree_ids") = std::vector<int>{}
        )
        .def("preload", &DTAGRuntime::preload)
        .def_property_readonly("tree_count", &DTAGRuntime::tree_count)
        .def_property_readonly("trees_dir", &DTAGRuntime::trees_dir)
        .def_property_readonly("run_dir", &DTAGRuntime::run_dir);
}
