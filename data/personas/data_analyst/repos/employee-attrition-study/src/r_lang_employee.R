library(dplyr)

build_employee <- function(df) {
  df %>% group_by(segment) %>% summarise(n = n(), mean_score = mean(score, na.rm = TRUE))
}
