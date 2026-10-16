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
#include <memory>
#include <unordered_map>
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

// Mean of per-tree (left, right) JSDs over trees where both are finite, summed in tree order:
// the exact reduction used by persistent_distances_to_state.
std::pair<double, double> reduce_pairs(const std::vector<double>& left_values,
                                       const std::vector<double>& right_values,
                                       const char* who) {
    double sum_left = 0.0;
    double sum_right = 0.0;
    size_t used = 0;
    for (size_t i = 0; i < left_values.size(); ++i) {
        const double dl = left_values[i];
        const double dr = right_values[i];
        if (std::isfinite(dl) && std::isfinite(dr)) {
            sum_left += dl;
            sum_right += dr;
            ++used;
        }
    }
    if (used == 0) throw std::runtime_error(std::string(who) + ": no usable trees");
    return {sum_left / static_cast<double>(used), sum_right / static_cast<double>(used)};
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

    // d(L, s u {col=token}) and d(R, s u {col=token}) for many single-column extensions of one
    // base state s, exactly equal to distances_to_state on each extended state.
    //   * pole predictions p_t(L), p_t(R) are cached across calls (they never change);
    //   * p_t(s) and the per-tree JSDs of the base state are computed once per call;
    //   * for an extension on column c only the trees that split on c are re-predicted; every
    //     other tree's prediction is provably unchanged (inference never reads column c).
    // Returns (base_dl, base_dr, [dl...], [dr...]).
    py::tuple extension_distances(
        const py::object& left,
        const py::object& right,
        const py::object& state,
        const std::vector<std::pair<int, std::string>>& extensions,
        std::vector<int> tree_ids
    ) {
        if (tree_ids.empty()) tree_ids = tree_ids_;
        const auto left_codes = store_.encodeRow(row_to_tokens(left));
        const auto right_codes = store_.encodeRow(row_to_tokens(right));
        const auto state_codes = store_.encodeRow(row_to_tokens(state));
        std::vector<int> ext_codes(extensions.size());
        for (size_t j = 0; j < extensions.size(); ++j) {
            const int col = extensions[j].first;
            if (col < 0 || static_cast<size_t>(col) >= state_codes.size()) {
                throw std::out_of_range("extension_distances: column out of range: " + std::to_string(col));
            }
            ext_codes[j] = store_.encodeToken(col, extensions[j].second);
        }

        std::vector<double> base_left(tree_ids.size(), 0.0), base_right(tree_ids.size(), 0.0);
        std::vector<double> out_left(extensions.size(), 0.0), out_right(extensions.size(), 0.0);
        std::pair<double, double> base;
        {
            py::gil_scoped_release release;
            const auto poles_ptr = pole_predictions(left_codes, right_codes, tree_ids);
            const PoleCache& poles = *poles_ptr;

            // Base state, and column -> positions of trees that split on it.
            std::vector<std::map<int, double>> p_state(tree_ids.size());
            std::unordered_map<int, std::vector<size_t>> trees_by_column;
            for (size_t i = 0; i < tree_ids.size(); ++i) {
                for (int col : predictor_.splitColumns(tree_ids[i])) trees_by_column[col].push_back(i);
            }
            run_parallel(tree_ids.size(), [&](size_t i) {
                p_state[i] = normalize_counts(predictor_.predict(tree_ids[i], state_codes));
                base_left[i] = jensen_shannon_bits(poles.left[i], p_state[i]);
                base_right[i] = jensen_shannon_bits(poles.right[i], p_state[i]);
            });
            base = reduce_pairs(base_left, base_right, "extension_distances");

            run_parallel(extensions.size(), [&](size_t j) {
                const int col = extensions[j].first;
                std::vector<double> lv = base_left, rv = base_right;
                auto found = trees_by_column.find(col);
                if (found != trees_by_column.end()) {
                    std::vector<int> codes = state_codes;
                    codes[static_cast<size_t>(col)] = ext_codes[j];
                    for (size_t i : found->second) {
                        const auto p = normalize_counts(predictor_.predict(tree_ids[i], codes));
                        lv[i] = jensen_shannon_bits(poles.left[i], p);
                        rv[i] = jensen_shannon_bits(poles.right[i], p);
                    }
                }
                const auto d = reduce_pairs(lv, rv, "extension_distances");
                out_left[j] = d.first;
                out_right[j] = d.second;
            });
        }
        return py::make_tuple(base.first, base.second, out_left, out_right);
    }

    // Columns each tree splits on (tree id -> sorted column ids).
    py::dict split_columns(std::vector<int> tree_ids) {
        if (tree_ids.empty()) tree_ids = tree_ids_;
        py::dict out;
        for (int tid : tree_ids) {
            const auto& cols = predictor_.splitColumns(tid);
            out[py::int_(tid)] = std::vector<int>(cols.begin(), cols.end());
        }
        return out;
    }

    void preload() {
        py::gil_scoped_release release;
        predictor_.preload(tree_ids_);
    }

    size_t tree_count() const { return tree_ids_.size(); }
    std::string trees_dir() const { return trees_dir_.string(); }
    std::string run_dir() const { return run_dir_.string(); }

private:
    struct PoleCache {
        std::vector<int> left_codes, right_codes, tree_ids;
        std::vector<std::map<int, double>> left, right;
    };

    template <typename Fn>
    void run_parallel(size_t n, Fn&& fn) {
        std::atomic<bool> failed{false};
        std::exception_ptr first_error;
        std::mutex error_mutex;
        parallel_for_indices(n, [&](size_t i) {
            if (failed.load(std::memory_order_relaxed)) return;
            try {
                fn(i);
            } catch (...) {
                failed.store(true, std::memory_order_relaxed);
                std::lock_guard<std::mutex> lock(error_mutex);
                if (!first_error) first_error = std::current_exception();
            }
        });
        if (first_error) std::rethrow_exception(first_error);
    }

    // Snapshot of the pole predictions; callers keep their own shared_ptr, so a concurrent call
    // with different poles can never invalidate data in use.
    std::shared_ptr<const PoleCache> pole_predictions(const std::vector<int>& left_codes,
                                                      const std::vector<int>& right_codes,
                                                      const std::vector<int>& tree_ids) {
        {
            std::lock_guard<std::mutex> lock(pole_mutex_);
            if (pole_cache_ && pole_cache_->left_codes == left_codes &&
                pole_cache_->right_codes == right_codes && pole_cache_->tree_ids == tree_ids) {
                return pole_cache_;
            }
        }
        auto fresh = std::make_shared<PoleCache>();
        fresh->left_codes = left_codes;
        fresh->right_codes = right_codes;
        fresh->tree_ids = tree_ids;
        fresh->left.resize(tree_ids.size());
        fresh->right.resize(tree_ids.size());
        run_parallel(tree_ids.size(), [&](size_t i) {
            fresh->left[i] = normalize_counts(predictor_.predict(tree_ids[i], left_codes));
            fresh->right[i] = normalize_counts(predictor_.predict(tree_ids[i], right_codes));
        });
        std::lock_guard<std::mutex> lock(pole_mutex_);
        pole_cache_ = fresh;
        return fresh;
    }

    std::mutex pole_mutex_;
    std::shared_ptr<const PoleCache> pole_cache_;
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
        .def(
            "extension_distances",
            &DTAGRuntime::extension_distances,
            py::arg("left"),
            py::arg("right"),
            py::arg("state"),
            py::arg("extensions"),
            py::arg("tree_ids") = std::vector<int>{}
        )
        .def(
            "split_columns",
            &DTAGRuntime::split_columns,
            py::arg("tree_ids") = std::vector<int>{}
        )
        .def("preload", &DTAGRuntime::preload)
        .def_property_readonly("tree_count", &DTAGRuntime::tree_count)
        .def_property_readonly("trees_dir", &DTAGRuntime::trees_dir)
        .def_property_readonly("run_dir", &DTAGRuntime::run_dir);
}
