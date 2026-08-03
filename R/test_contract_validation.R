#!/usr/bin/env Rscript

source(file.path("R", "reference_metrics.R"))

source_case <- file.path("cases", "unmapped-program-retention")

copy_case <- function() {
  destination <- tempfile("edge-contract-")
  dir.create(destination)
  copied <- file.copy(
    list.files(source_case, full.names = TRUE),
    destination,
    recursive = FALSE
  )
  if (!all(copied)) {
    stop("Could not create temporary contract fixture")
  }
  destination
}

rewrite_csv <- function(case_dir, filename, mutate) {
  path <- file.path(case_dir, filename)
  rows <- read.csv(
    path,
    stringsAsFactors = FALSE,
    check.names = FALSE,
    colClasses = "character",
    na.strings = character()
  )
  rows <- mutate(rows)
  write.table(
    rows,
    path,
    sep = ",",
    row.names = FALSE,
    col.names = TRUE,
    quote = FALSE,
    na = ""
  )
}

expect_error <- function(label, mutate) {
  case_dir <- copy_case()
  on.exit(unlink(case_dir, recursive = TRUE), add = TRUE)
  mutate(case_dir)
  failed <- FALSE
  tryCatch(
    compute_reference(case_dir),
    error = function(error) {
      failed <<- TRUE
    }
  )
  if (!failed) {
    stop(sprintf("Expected contract validation error: %s", label))
  }
}

expect_success <- function(label, mutate) {
  case_dir <- copy_case()
  on.exit(unlink(case_dir, recursive = TRUE), add = TRUE)
  mutate(case_dir)
  tryCatch(
    compute_reference(case_dir),
    error = function(error) {
      stop(sprintf("Expected valid contract for %s: %s", label, error$message))
    }
  )
}

expect_error("invalid timestamp", function(case_dir) {
  rewrite_csv(case_dir, "referrals.csv", function(rows) {
    rows$referred_at[1] <- "2026-02-30T08:00:00Z"
    rows
  })
})

expect_error("reversed reporting period", function(case_dir) {
  rewrite_csv(case_dir, "reporting_periods.csv", function(rows) {
    rows$start_date[1] <- "2026-08-31"
    rows$end_date[1] <- "2026-08-01"
    rows
  })
})

expect_error("dangling referral", function(case_dir) {
  rewrite_csv(case_dir, "encounters.csv", function(rows) {
    rows$referral_id[1] <- "R-MISSING"
    rows
  })
})

expect_error("dangling appointment", function(case_dir) {
  rewrite_csv(case_dir, "encounters.csv", function(rows) {
    rows$appointment_id[1] <- "A-MISSING"
    rows
  })
})

expect_success("equal one-day period", function(case_dir) {
  rewrite_csv(case_dir, "reporting_periods.csv", function(rows) {
    rows$end_date[1] <- rows$start_date[1]
    rows
  })
})

expect_success("valid leap day", function(case_dir) {
  rewrite_csv(case_dir, "referrals.csv", function(rows) {
    rows$referred_at[1] <- "2024-02-29T08:00:00Z"
    rows
  })
})

cat("PASS  R contract validation controls\n")
