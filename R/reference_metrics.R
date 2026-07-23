# Independent, dependency-free R implementation of the suite's reference rules.

read_case_csv <- function(case_dir, filename) {
  path <- file.path(case_dir, filename)
  if (!file.exists(path)) {
    stop(sprintf("Required file is missing: %s", path))
  }
  data <- read.csv(
    path,
    stringsAsFactors = FALSE,
    check.names = FALSE,
    colClasses = "character",
    na.strings = character()
  )
  if (nrow(data) == 0) {
    stop(sprintf("%s must contain at least one data row", path))
  }
  data
}

current_encounters <- function(encounters) {
  ordered <- order(
    encounters$source_event_id,
    -as.integer(encounters$version),
    -xtfrm(encounters$updated_at),
    -xtfrm(encounters$encounter_row_id)
  )
  candidates <- encounters[ordered, , drop = FALSE]
  candidates[!duplicated(candidates$source_event_id), , drop = FALSE]
}

parse_fixture_time <- function(values) {
  as.POSIXct(
    values,
    format = "%Y-%m-%dT%H:%M:%OSZ",
    tz = "UTC"
  )
}

append_metric <- function(metrics, period_id, metric_id, value) {
  rbind(
    metrics,
    data.frame(
      period_id = period_id,
      metric_id = metric_id,
      actual_value = as.integer(value),
      stringsAsFactors = FALSE
    )
  )
}

compute_reference <- function(case_dir) {
  mappings <- read_case_csv(case_dir, "program_mappings.csv")
  referrals <- read_case_csv(case_dir, "referrals.csv")
  appointments <- read_case_csv(case_dir, "appointments.csv")
  encounters <- read_case_csv(case_dir, "encounters.csv")
  periods <- read_case_csv(case_dir, "reporting_periods.csv")

  current <- current_encounters(encounters)
  qualifying <- current[tolower(current$status) == "completed", , drop = FALSE]
  qualifying_dates <- as.Date(substr(qualifying$occurred_at, 1, 10))
  encounter_dates <- as.Date(substr(encounters$occurred_at, 1, 10))
  referral_dates <- as.Date(substr(referrals$referred_at, 1, 10))

  mapping_index <- match(qualifying$program_id, mappings$program_id)
  mapping_values <- mappings$reporting_program[mapping_index]
  mapped <- !is.na(mapping_index) &
    !is.na(mapping_values) &
    mapping_values != ""

  metrics <- data.frame(
    period_id = character(),
    metric_id = character(),
    actual_value = integer(),
    stringsAsFactors = FALSE
  )

  for (index in seq_len(nrow(periods))) {
    period <- periods[index, , drop = FALSE]
    period_start <- as.Date(period$start_date)
    period_end <- as.Date(period$end_date)
    raw_in_period <- tolower(encounters$status) == "completed" &
      encounter_dates >= period_start &
      encounter_dates <= period_end
    qualifying_in_period <- qualifying_dates >= period_start &
      qualifying_dates <= period_end
    referrals_in_period <- referral_dates >= period_start &
      referral_dates <= period_end

    referrals_with_service <- sum(vapply(
      which(referrals_in_period),
      function(referral_index) {
        referral_id <- referrals$referral_id[referral_index]
        referred_at <- parse_fixture_time(
          referrals$referred_at[referral_index]
        )
        service_times <- parse_fixture_time(
          qualifying$occurred_at[
            qualifying$referral_id == referral_id &
              qualifying$referral_id != ""
          ]
        )
        any(service_times >= referred_at)
      },
      logical(1)
    ))

    metrics <- append_metric(
      metrics,
      period$period_id,
      "raw_completed_rows",
      sum(raw_in_period)
    )
    metrics <- append_metric(
      metrics,
      period$period_id,
      "completed_service_events",
      sum(qualifying_in_period)
    )
    metrics <- append_metric(
      metrics,
      period$period_id,
      "unique_patients_served",
      length(unique(qualifying$patient_id[qualifying_in_period]))
    )
    metrics <- append_metric(
      metrics,
      period$period_id,
      "mapped_completed_events",
      sum(qualifying_in_period & mapped)
    )
    metrics <- append_metric(
      metrics,
      period$period_id,
      "unmapped_completed_events",
      sum(qualifying_in_period & !mapped)
    )
    metrics <- append_metric(
      metrics,
      period$period_id,
      "referrals_started",
      sum(referrals_in_period)
    )
    metrics <- append_metric(
      metrics,
      period$period_id,
      "referrals_with_first_service",
      referrals_with_service
    )
  }

  appointment_index <- match(
    qualifying$appointment_id,
    appointments$appointment_id
  )
  appointment_status <- appointments$status[appointment_index]
  referral_index <- match(qualifying$referral_id, referrals$referral_id)
  linked_referral_time <- parse_fixture_time(
    referrals$referred_at[referral_index]
  )
  qualifying_time <- parse_fixture_time(qualifying$occurred_at)
  completed_appointment_ids <- appointments$appointment_id[
    tolower(appointments$status) == "completed"
  ]

  quality <- data.frame(
    check_id = c(
      "source_events_with_multiple_versions",
      "current_voided_events",
      "unmapped_completed_encounters",
      "completed_encounter_cancelled_appointment",
      "completed_encounter_before_referral",
      "completed_appointments_without_completed_encounter"
    ),
    actual_value = as.integer(c(
      sum(table(encounters$source_event_id) > 1),
      sum(tolower(current$status) == "voided"),
      sum(!mapped),
      sum(
        qualifying$appointment_id != "" &
          !is.na(appointment_index) &
          tolower(appointment_status) %in% c("cancelled", "canceled")
      ),
      sum(
        qualifying$referral_id != "" &
          !is.na(referral_index) &
          qualifying_time < linked_referral_time,
        na.rm = TRUE
      ),
      sum(!completed_appointment_ids %in% qualifying$appointment_id)
    )),
    stringsAsFactors = FALSE
  )

  list(metrics = metrics, quality = quality)
}

compare_expected <- function(case_dir, filename, actual, keys) {
  expected <- read_case_csv(case_dir, filename)
  expected_key <- do.call(paste, c(expected[keys], sep = "\r"))
  actual_key <- do.call(paste, c(actual[keys], sep = "\r"))

  expected_values <- setNames(
    as.integer(expected$expected_value),
    expected_key
  )
  actual_values <- setNames(
    as.integer(actual$actual_value),
    actual_key
  )

  missing <- setdiff(names(expected_values), names(actual_values))
  unexpected <- setdiff(names(actual_values), names(expected_values))
  shared <- intersect(names(expected_values), names(actual_values))
  wrong <- shared[expected_values[shared] != actual_values[shared]]

  if (length(missing) + length(unexpected) + length(wrong) > 0) {
    details <- c(
      if (length(missing)) paste("missing", paste(missing, collapse = ", ")),
      if (length(unexpected)) {
        paste("unexpected", paste(unexpected, collapse = ", "))
      },
      if (length(wrong)) {
        paste(
          "wrong",
          paste(
            sprintf(
              "%s expected=%s actual=%s",
              wrong,
              expected_values[wrong],
              actual_values[wrong]
            ),
            collapse = ", "
          )
        )
      }
    )
    stop(sprintf("%s: %s", filename, paste(details, collapse = "; ")))
  }

  nrow(expected)
}

run_case_reference <- function(case_dir) {
  result <- compute_reference(case_dir)
  metric_count <- compare_expected(
    case_dir,
    "expected_metrics.csv",
    result$metrics,
    c("period_id", "metric_id")
  )
  quality_count <- compare_expected(
    case_dir,
    "expected_quality.csv",
    result$quality,
    "check_id"
  )
  metric_count + quality_count
}
