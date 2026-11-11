library(dplyr)

score_customer <- function(df) {
  df %>% group_by(segment) %>% summarise(n = n(), mean_score = mean(score, na.rm = TRUE))
}
