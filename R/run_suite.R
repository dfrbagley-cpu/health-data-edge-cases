#!/usr/bin/env Rscript

source(file.path("R", "reference_metrics.R"))

case_root <- "cases"
case_dirs <- sort(list.dirs(case_root, recursive = FALSE, full.names = TRUE))
case_dirs <- case_dirs[file.exists(file.path(case_dirs, "case.json"))]

if (length(case_dirs) == 0) {
  stop("No cases found")
}

failed <- FALSE
expectation_count <- 0L

for (case_dir in case_dirs) {
  case_id <- basename(case_dir)
  tryCatch(
    {
      count <- run_case_reference(case_dir)
      expectation_count <- expectation_count + count
      cat(sprintf("PASS  %s  (%d expectations)\n", case_id, count))
    },
    error = function(error) {
      failed <<- TRUE
      cat(sprintf("FAIL  %s\n      %s\n", case_id, conditionMessage(error)))
    }
  )
}

if (failed) {
  quit(status = 1)
}

cat(sprintf(
  "PASS  R reference: %d/%d cases, %d expectations\n",
  length(case_dirs),
  length(case_dirs),
  expectation_count
))
