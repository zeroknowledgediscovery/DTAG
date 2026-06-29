# Master DTAG question set

This folder combines the original DTAG question sets and the divergence-probe question sets into one clean experiment folder.

Files are numbered so lexicographic sorting matches the intended grouping. The original question sets were renamed to content-based filenames, and the divergence probes were also zero-padded to avoid `diverge_set_10` sorting before `diverge_set_1`.

Only runnable question CSVs are stored here. Manifests and label maps are stored under `assets/label_maps/`, not in this folder, so the experiment launcher cannot accidentally run them as question sets.
