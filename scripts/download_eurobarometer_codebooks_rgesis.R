#!/usr/bin/env Rscript

# Download GESIS Eurobarometer codebooks/Variable Reports for every installed
# native Eurobarometer model. Requires a working rgesis authentication:
#
#   library(rgesis)
#   gesis_auth()
#   gesis_can_auth()   # must be TRUE
#
# Usage from DTAG root:
#
#   Rscript scripts/download_eurobarometer_codebooks_rgesis.R
#
# Optional:
#   Rscript scripts/download_eurobarometer_codebooks_rgesis.R --limit 5
#   Rscript scripts/download_eurobarometer_codebooks_rgesis.R --za ZA7575
#
# Existing valid PDFs are skipped. Failures are recorded and the script
# continues so it is safe to rerun.

suppressPackageStartupMessages(library(rgesis))

args <- commandArgs(trailingOnly = TRUE)

get_arg <- function(flag, default = NULL) {
  i <- match(flag, args)
  if (is.na(i) || i == length(args)) return(default)
  args[[i + 1]]
}

has_flag <- function(flag) flag %in% args

limit <- as.integer(get_arg("--limit", "0"))
one_za <- get_arg("--za", "")
delay <- as.numeric(get_arg("--delay", "1.5"))

MODEL_ROOT <- "models/lsm/eurobarometer"
OUT_ROOT <- "data/eurobarometer/codebooks"
dir.create(OUT_ROOT, recursive = TRUE, showWarnings = FALSE)

if (!dir.exists(MODEL_ROOT)) {
  stop("Missing model directory: ", MODEL_ROOT)
}

if (!gesis_can_auth()) {
  stop(
    "rgesis authentication is not available. Run interactive R:\n",
    "  library(rgesis)\n",
    "  gesis_auth()\n",
    "  gesis_can_auth()\n"
  )
}

dirs <- list.dirs(MODEL_ROOT, recursive = FALSE, full.names = FALSE)
za <- unique(toupper(sub("^(ZA[0-9]+).*", "\\1", dirs)))
za <- za[grepl("^ZA[0-9]+$", za)]
za <- za[order(as.integer(sub("^ZA", "", za)))]

if (nzchar(one_za)) {
  one_za <- toupper(one_za)
  if (!grepl("^ZA[0-9]+$", one_za)) stop("Invalid --za: ", one_za)
  za <- one_za
}

if (limit > 0) za <- head(za, limit)

valid_pdf <- function(path) {
  if (!file.exists(path) || file.info(path)$size < 1000) return(FALSE)
  con <- file(path, "rb")
  on.exit(close(con), add = TRUE)
  identical(rawToChar(readBin(con, "raw", n = 4)), "%PDF")
}

file_label <- function(x) {
  vals <- list(x$label_en, x$label, x$file_name)
  for (v in vals) {
    if (!is.null(v) && length(v) && !is.na(v[[1]]) && nzchar(as.character(v[[1]]))) {
      return(as.character(v[[1]]))
    }
  }
  ""
}

score_label <- function(label, type) {
  x <- tolower(label)
  score <- 0
  if (grepl("variable report", x, fixed = TRUE)) score <- score + 10000
  if (grepl("codebook", x, fixed = TRUE)) score <- score + 8000
  if (grepl("_cdb\\.pdf", x)) score <- score + 7000
  if (type == "codebook") score <- score + 5000
  if (grepl("variable", x, fixed = TRUE)) score <- score + 1500
  if (grepl("report", x, fixed = TRUE)) score <- score + 700
  if (grepl("\\.pdf", x)) score <- score + 300
  if (grepl("questionnaire", x, fixed = TRUE)) score <- score - 4000
  if (grepl("basic bilingual", x, fixed = TRUE)) score <- score - 2500
  score
}

regex_escape <- function(x) {
  gsub("([][{}()+*^$|\\\\?.])", "\\\\\\1", x)
}

choose_candidate <- function(id) {
  types <- tryCatch(
    gesis_file_types(id),
    error = function(e) stop("gesis_file_types failed: ", conditionMessage(e))
  )

  if (is.null(types) || !length(types)) {
    stop("No downloadable files listed")
  }

  # Prefer codebook, but older records sometimes classify documentation as
  # otherdocs/report/other.
  preferred <- c("codebook", "otherdocs", "other", "report", "questionnaire")
  preferred <- preferred[preferred %in% types]

  candidates <- list()

  for (tp in preferred) {
    ff <- tryCatch(gesis_files(id, type = tp), error = function(e) NULL)
    if (is.null(ff) || !length(ff)) next

    for (i in seq_along(ff)) {
      lab <- file_label(ff[[i]])
      if (!nzchar(lab)) next
      # We only want PDF-like documentation.
      fmt <- ff[[i]]$format
      is_pdf <- grepl("\\.pdf", lab, ignore.case = TRUE) ||
        (!is.null(fmt) && grepl("pdf", as.character(fmt), ignore.case = TRUE))
      if (!is_pdf) next

      candidates[[length(candidates) + 1]] <- list(
        type = tp,
        label = lab,
        score = score_label(lab, tp)
      )
    }
  }

  if (!length(candidates)) stop("No PDF documentation candidate found")

  scores <- vapply(candidates, function(x) x$score, numeric(1))
  candidates[[which.max(scores)]]
}

download_one <- function(id, outfile) {
  cand <- choose_candidate(id)

  cat("selected type: ", cand$type, "\n", sep = "")
  cat("selected file: ", cand$label, "\n", sep = "")
  cat("selection score: ", cand$score, "\n", sep = "")

  # Use an exact escaped label when there are multiple files in the category.
  ff <- gesis_files(id, type = cand$type)
  labels <- vapply(ff, file_label, character(1))

  if (length(labels) == 1) {
    select <- NULL
  } else {
    select <- paste0("^", regex_escape(cand$label), "$")
  }

  gesis_data(
    id,
    type = cand$type,
    select = select,
    download_purpose = "scientific_research",
    path = outfile,
    prompt = FALSE,
    overwrite = TRUE
  )

  if (!valid_pdf(outfile)) {
    stop("Downloaded file is missing or is not a valid PDF")
  }

  invisible(outfile)
}

cat("Authenticated rgesis:", gesis_can_auth(), "\n")
cat("Installed Eurobarometer models:", length(za), "\n")
cat("Output:", OUT_ROOT, "\n\n")

ok <- character()
skip <- character()
fail <- character()

for (i in seq_along(za)) {
  id <- za[[i]]
  outfile <- file.path(OUT_ROOT, paste0(id, "_cdb.pdf"))

  cat("========================================================================\n")
  cat(sprintf("[%d/%d] %s\n", i, length(za), id))

  if (valid_pdf(outfile)) {
    cat("SKIP existing valid PDF:", outfile, "\n")
    skip <- c(skip, id)
    next
  }

  success <- tryCatch({
    download_one(id, outfile)
    cat(sprintf(
      "DONE: %s (%.2f MiB)\n",
      outfile,
      file.info(outfile)$size / 1024^2
    ))
    TRUE
  }, error = function(e) {
    cat("FAILED:", conditionMessage(e), "\n")
    FALSE
  })

  if (success) ok <- c(ok, id) else fail <- c(fail, id)

  if (i < length(za) && delay > 0) Sys.sleep(delay)
}

cat("\n========================================================================\n")
cat("SUMMARY\n")
cat("downloaded:", length(ok), "\n")
cat("already present:", length(skip), "\n")
cat("failed:", length(fail), "\n")

if (length(fail)) {
  cat("failed ZA ids:\n")
  cat(paste(fail, collapse = " "), "\n")
  writeLines(fail, file.path(OUT_ROOT, "failed_rgesis_downloads.txt"))
}
