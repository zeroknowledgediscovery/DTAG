#include "PredictDistribution/PredictDistribution.h"
#include "Tree/Tree.h"

#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <mutex>

using namespace std;

namespace {

map<int, double> normalize(const map<int, int>& counts, const TreeNode* node = nullptr) {
    double total = 0.0;
    for (const auto& kv : counts) total += static_cast<double>(kv.second);
    if (total <= 0.0) {
        if (node) {
            throw logic_error(
                "normalize: total count <= 0 at leaf node " + to_string(node->getId()) +
                " observationCount=" + to_string(node->getObservationCount()) +
                " featureCounts.size=" + to_string(counts.size())
            );
        }
        throw logic_error("normalize: total count <= 0");
    }

    map<int, double> probs;
    for (const auto& kv : counts) probs[kv.first] = static_cast<double>(kv.second) / total;
    return probs;
}

map<int, double> mix_probs(const map<int, double>& pLeft,
                           const map<int, double>& pRight,
                           double pi) {
    map<int, double> output = pLeft;
    for (const auto& kv : pRight) if (!output.count(kv.first)) output[kv.first] = 0.0;
    for (auto& kv : output) {
        const double a = pLeft.count(kv.first) ? pLeft.at(kv.first) : 0.0;
        const double b = pRight.count(kv.first) ? pRight.at(kv.first) : 0.0;
        kv.second = pi * a + (1.0 - pi) * b;
    }
    return output;
}

double subtree_mass(TreeNode* node,
                    unordered_map<const TreeNode*, double>& memo) {
    const auto found = memo.find(node);
    if (found != memo.end()) return found->second;

    double mass = 0.0;
    if (node->isLeaf()) {
        for (const auto& kv : node->getFeatureCounts()) mass += static_cast<double>(kv.second);
    } else {
        SplitNode* split = static_cast<SplitNode*>(node);
        if (!split->hasLeft() || !split->hasRight()) throw logic_error("subtree_mass: split is missing a child");
        mass = subtree_mass(split->getLeft(), memo) + subtree_mass(split->getRight(), memo);
    }
    if (mass <= 0.0) throw logic_error("subtree_mass: subtree has zero target mass");
    memo[node] = mass;
    return mass;
}

map<int, double> infer(TreeNode* node,
                       const vector<int>& values,
                       unordered_map<const TreeNode*, double>& massMemo) {
    if (node->isLeaf()) return normalize(node->getFeatureCounts(), node);

    SplitNode* split = static_cast<SplitNode*>(node);
    const int columnID = split->getColumnID();
    if (columnID < 0 || static_cast<size_t>(columnID) >= values.size()) {
        throw out_of_range("infer: column ID out of range: " + to_string(columnID));
    }

    const int v = values[static_cast<size_t>(columnID)];
    if (v != 0 && split->getLeftSubset().count(v)) {
        if (!split->hasLeft()) throw logic_error("infer: missing left child");
        return infer(split->getLeft(), values, massMemo);
    }
    if (v != 0 && split->getRightSubset().count(v)) {
        if (!split->hasRight()) throw logic_error("infer: missing right child");
        return infer(split->getRight(), values, massMemo);
    }

    if (!split->hasLeft() || !split->hasRight()) throw logic_error("infer: missing child at split during marginalization");

    const double nLeft = subtree_mass(split->getLeft(), massMemo);
    const double nRight = subtree_mass(split->getRight(), massMemo);
    const double denominator = nLeft + nRight;
    if (denominator <= 0.0) throw logic_error("infer: constructed child mass <= 0");
    const double pi = nLeft / denominator;

    const map<int, double> pLeft = infer(split->getLeft(), values, massMemo);
    const map<int, double> pRight = infer(split->getRight(), values, massMemo);
    return mix_probs(pLeft, pRight, pi);
}

map<int, int> probs_to_pseudocounts(const map<int, double>& probs, int scale = 1000000) {
    map<int, int> output;
    for (const auto& kv : probs) output[kv.first] = static_cast<int>(std::llround(kv.second * static_cast<double>(scale)));
    long long sum = 0;
    for (const auto& kv : output) sum += kv.second;
    if (sum == 0) throw logic_error("probs_to_pseudocounts: rounded to zero");
    return output;
}

}

PredictDistribution::PredictDistribution(const std::string& dirPath)
    : directory(dirPath) {}

shared_ptr<Tree> PredictDistribution::getTree(int treeId) const {
    {
        shared_lock<shared_mutex> lock(treeCacheMutex);
        auto it = treeCache.find(treeId);
        if (it != treeCache.end()) return it->second;
    }

    unique_lock<shared_mutex> lock(treeCacheMutex);
    auto it = treeCache.find(treeId);
    if (it != treeCache.end()) return it->second;

    ostringstream filename;
    filename << directory << "/tree_" << treeId << ".bin";
    ifstream inFile(filename.str(), ios::binary);
    if (!inFile) throw runtime_error("Could not open tree file: " + filename.str());

    auto tree = make_shared<Tree>(inFile);
    if (!tree->getRoot()) throw runtime_error("Tree has no root");
    treeCache.emplace(treeId, tree);
    return tree;
}

void PredictDistribution::preload(const vector<int>& treeIds) const {
    for (int treeId : treeIds) (void)getTree(treeId);
}

map<int, int> PredictDistribution::predict(int treeId, const vector<int>& values) const {
    const auto tree = getTree(treeId);
    TreeNode* root = tree->getRoot();
    if (!root) throw runtime_error("Tree has no root");

    unordered_map<const TreeNode*, double> massMemo;
    const map<int, double> probs = infer(root, values, massMemo);
    return probs_to_pseudocounts(probs);
}
