# Independent base R interpretation of the bundled synthetic reporting packs.
root <- file.path("health_edge_cases", "packs")
read_input <- function(pack, name) read.csv(file.path(root, pack, paste0("input_", name, ".csv")), colClasses="character", na.strings=NULL)
verify <- function(pack, actual) {
  expected <- read.csv(file.path(root, pack, "expected.csv"), colClasses=c("character", "integer"))
  stopifnot(setequal(names(actual), expected$check))
  stopifnot(all(actual[expected$check] == expected$value))
  cat(sprintf("PASS  %s (%d expectations)\n", pack, nrow(expected)))
}

r <- read_input("referral-chronology", "referrals")
r <- r[r$referred_on <= r$cutoff, ]
verify("referral-chronology", c(cohort=nrow(r),
  completed=sum(r$first_service_on >= r$referred_on & r$first_service_on <= r$cutoff),
  same_day=sum(r$first_service_on == r$referred_on),
  ongoing=sum(r$first_service_on == "" | r$first_service_on > r$cutoff),
  invalid_sequence=sum(r$first_service_on != "" & r$first_service_on < r$referred_on)))

e <- read_input("historical-cutoff", "events")
latest <- function(rows) {
  rows <- rows[order(rows$event_id, -as.integer(rows$version)), ]
  rows[!duplicated(rows$event_id), ]
}
count_services <- function(rows) sum(rows$status == "completed" & rows$service_on >= "2026-08-01" & rows$service_on <= "2026-08-31")
known <- latest(e[e$known_on <= "2026-08-31", ])
verify("historical-cutoff", c(known_at_cutoff=count_services(known), latest_revised=count_services(latest(e)),
  late_arrivals=sum(e$version == "1" & e$known_on > "2026-08-31" & e$service_on <= "2026-08-31"),
  post_cutoff_corrections=sum(as.integer(e$version)>1 & e$known_on > "2026-08-31"),
  included_on_boundary=sum(known$known_on == "2026-08-31" & known$status == "completed")))

e <- read_input("effective-dated-mappings", "events")
m <- read_input("effective-dated-mappings", "mappings")
matches <- lapply(seq_len(nrow(e)), function(i) m$category[m$program == e$program[i] & m$valid_from <= e$service_on[i] & m$valid_to > e$service_on[i]])
sizes <- lengths(matches)
verify("effective-dated-mappings", c(events=nrow(e), mapped_once=sum(sizes==1), unmapped=sum(sizes==0), ambiguous=sum(sizes>1),
  old_category=sum(vapply(matches, function(x) identical(x, "old"), logical(1))),
  new_category=sum(vapply(matches, function(x) identical(x, "new"), logical(1)))))
