"""BM25, written by hand so I understand every term.

For a query q (my skills) and a document d (one job's text):

    score(q, d) = sum over terms t in q of
        IDF(t) * tf(t,d) * (k1 + 1) / ( tf(t,d) + k1 * (1 - b + b * |d| / avgdl) )

    IDF(t) = ln( (N - df(t) + 0.5) / (df(t) + 0.5) + 1 )

  tf(t,d) -- how often t appears in d. More is better, but with diminishing
             returns: the k1 term caps it (k1 = 1.5 is the usual default).
  |d|     -- document length; avgdl is the average. b = 0.75 punishes long
             JDs a bit, because a long JD mentions everything once.
  IDF     -- rare terms matter more. "Python" in 30% of jobs says less than
             "RAG" in 2% of jobs.

Why not plain keyword counting: counting rewards long JDs that list every
buzzword, and treats "Python" and "RAG" as equally informative. BM25 fixes both.
"""
import math
import re
from collections import Counter


def tokenize(text):
    """English words as-is, Chinese as character bigrams ("推荐系统" -> 推荐 荐系 系统)."""
    text = (text or "").lower()
    tokens = re.findall(r"[a-z][a-z0-9+#.]*", text)
    for run in re.findall(r"[一-鿿]+", text):
        if len(run) == 1:
            tokens.append(run)
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.N = len(docs)
        self.avgdl = (sum(self.lens) / self.N) if self.N else 0
        df = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        self.idf = {t: math.log((self.N - n + 0.5) / (n + 0.5) + 1) for t, n in df.items()}

    def score(self, query):
        q = set(query)
        out = []
        for tf, dl in zip(self.tfs, self.lens):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * dl / self.avgdl) if self.avgdl else self.k1
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out
