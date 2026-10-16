#ifndef PREDICT_DISTRIBUTION_H
#define PREDICT_DISTRIBUTION_H

#include <map>
#include <memory>
#include <set>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <vector>

using namespace std;

class Tree;
class TreeNode;

class PredictDistribution {
    private:
        string directory;
        // A loaded tree together with the target mass of every subtree. The masses depend only
        // on the tree, so they are computed once at load instead of on every predict() call.
        struct LoadedTree {
            shared_ptr<Tree> tree;
            unordered_map<const TreeNode*, double> mass;
            set<int> splitColumns;
        };
        mutable unordered_map<int, shared_ptr<const LoadedTree>> treeCache;
        mutable shared_mutex treeCacheMutex;

        shared_ptr<const LoadedTree> getTree(int treeId) const;

    public:
        explicit PredictDistribution(const string& dirPath);
        void preload(const vector<int>& treeIds) const;
        map<int, int> predict(int treeId, const vector<int>& values) const;
        // Columns this tree splits on. Its prediction cannot change when any other column changes.
        const set<int>& splitColumns(int treeId) const;
};

#endif // PREDICT_DISTRIBUTION_H
