from . import beisen, campus_radar, feishu, guopin, hotjob, pingan

SCRAPERS = {
    "feishu": feishu.fetch,
    "beisen": beisen.fetch,
    "guopin": guopin.fetch,
    "campus_radar": campus_radar.fetch,
    "pingan": pingan.fetch,
    "hotjob": hotjob.fetch,
}
