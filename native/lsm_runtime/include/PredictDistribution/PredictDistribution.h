#ifndef PREDICT_DISTRIBUTION_H
#define PREDICT_DISTRIBUTION_H

#include <map>
#include <memory>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <vector>

using namespace std;

class Tree;

class PredictDistribution {
    private:
        string directory;
        mutable unordered_map<int, shared_ptr<Tree>> treeCache;
        mutable shared_mutex treeCacheMutex;

        shared_ptr<Tree> getTree(int treeId) const;

    public:
        explicit PredictDistribution(const string& dirPath);
        void preload(const vector<int>& treeIds) const;
        map<int, int> predict(int treeId, const vector<int>& values) const;
};

#endif // PREDICT_DISTRIBUTION_H
