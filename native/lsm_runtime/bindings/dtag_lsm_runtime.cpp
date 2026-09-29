#include "PredictDistribution/PredictDistribution.h"
#include "QDistance/qdistance.h"
#include "SourceMaps/SourceMaps.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <filesystem>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <exception>
#include <map>
#include <mutex>
#include <thread>
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

std::map<int, double> normalize_counts(const std::map<int, int>& counts) {
    long long total = 0;
    for (const auto& kv : counts) total += kv.second;
    if (total <= 0) {
        throw std::logic_error("normalize_counts: total count <= 0");
    }
    std::map<int, double> out;
    for (const auto& kv : counts) {
        out.emplace(
            kv.first,
            static_cast<double>(kv.second) / static_cast<double>(total)
        );
    }
    return out;
}

template <typename Fn>
void parallel_for_indices(size_t n, Fn&& fn) {
    if (n == 0) return;

    unsigned int hw = std::thread::hardware_concurrency();
    size_t workers = hw > 0 ? static_cast<size_t>(hw) : 4u;

    // Tree-level work is moderately coarse; avoid excessive thread creation.
    workers = std::min(workers, static_cast<size_t>(16));
    workers = std::min(workers, n);

    if (workers <= 1 || n < 16) {
        for (size_t i = 0; i < n; ++i) fn(i);
        return;
    }

    std::atomic<size_t> next{0};
    std::vector<std::thread> pool;
    pool.reserve(workers);

    for (size_t w = 0; w < workers; ++w) {
        pool.emplace_back([&]() {
            while (true) {
                const size_t i = next.fetch_add(1, std::memory_order_relaxed);
                if (i >= n) break;
                fn(i);
            }
        });
    }

    for (auto& t : pool) t.join();
}

double persistent_qdistance(
    const PredictDistribution& predictor,
    const std::vector<int>& row_a,
    const std::vector<int>& row_b,
    const std::vector<int>& tree_ids
) {
    std::vector<double> values(tree_ids.size(), 0.0);
    std::atomic<bool> failed{false};
    std::exception_ptr first_error;
    std::mutex error_mutex;

    parallel_for_indices(tree_ids.size(), [&](size_t i) {
        if (failed.load(std::memory_order_relaxed)) return;
        try {
            const int tid = tree_ids[i];
            const auto p_a = normalize_counts(predictor.predict(tid, row_a));
            const auto p_b = normalize_counts(predictor.predict(tid, row_b));
            values[i] = jensen_shannon_bits(p_a, p_b);
        } catch (...) {
            failed.store(true, std::memory_order_relaxed);
            std::lock_guard<std::mutex> lock(error_mutex);
            if (!first_error) first_error = std::current_exception();
        }
    });

    if (first_error) std::rethrow_exception(first_error);

    double sum = 0.0;
    size_t used = 0;
    for (double v : values) {
        if (std::isfinite(v)) {
            sum += v;
            ++used;
        }
    }
    if (used == 0) throw std::runtime_error("persistent_qdistance: no usable trees");
    return sum / static_cast<double>(used);
}

std::pair<double, double> persistent_distances_to_state(
    const PredictDistribution& predictor,
    const std::vector<int>& left,
    const std::vector<int>& right,
    const std::vector<int>& state,
    const std::vector<int>& tree_ids
) {
    std::vector<double> left_values(tree_ids.size(), 0.0);
    std::vector<double> right_values(tree_ids.size(), 0.0);
    std::atomic<bool> failed{false};
    std::exception_ptr first_error;
    std::mutex error_mutex;

    parallel_for_indices(tree_ids.size(), [&](size_t i) {
        if (failed.load(std::memory_order_relaxed)) return;
        try {
            const int tid = tree_ids[i];

            // State is evaluated once for this tree and reused for both poles.
            const auto p_state = normalize_counts(predictor.predict(tid, state));
            const auto p_left = normalize_counts(predictor.predict(tid, left));
            const auto p_right = normalize_counts(predictor.predict(tid, right));

            left_values[i] = jensen_shannon_bits(p_left, p_state);
            right_values[i] = jensen_shannon_bits(p_right, p_state);
        } catch (...) {
            failed.store(true, std::memory_order_relaxed);
            std::lock_guard<std::mutex> lock(error_mutex);
            if (!first_error) first_error = std::current_exception();
        }
    });

    if (first_error) std::rethrow_exception(first_error);

    double sum_left = 0.0;
    double sum_right = 0.0;
    size_t used = 0;
    for (size_t i = 0; i < tree_ids.size(); ++i) {
        const double dl = left_values[i];
        const double dr = right_values[i];
        if (std::isfinite(dl) && std::isfinite(dr)) {
            sum_left += dl;
            sum_right += dr;
            ++used;
        }
    }

    if (used == 0) {
        throw std::runtime_error("persistent_distances_to_state: no usable trees");
    }

    return {
        sum_left / static_cast<double>(used),
        sum_right / static_cast<double>(used)
    };
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
        return persistent_qdistance(predictor_, a_codes, b_codes, tree_ids);
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

        std::pair<double, double> distances;
        {
            py::gil_scoped_release release;
            distances = persistent_distances_to_state(
                predictor_,
                left_codes,
                right_codes,
                state_codes,
                tree_ids
            );
        }

        return py::make_tuple(distances.first, distances.second);
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
