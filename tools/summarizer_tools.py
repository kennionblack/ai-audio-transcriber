from collections import Counter
import re
from tools import ToolBox

# This is kind of a really poor approach but I wanted to try something without just feeding the text back to another AI. 

# Basic list of common stopwords
STOPWORDS = {
    "the", "and", "a", "an", "of", "in", "on", "at", "to", "for",
    "with", "is", "are", "was", "were", "be", "by", "this", "that",
    "it", "from", "as", "or", "but", "if", "then", "so", "not"
}

def get_n_most_common_words(text: str, n: int) -> str:
    """
    Extract the n most common words from the text. 
    """
    # Normalize text to lowercase and split into words
    words = re.findall(r'\b\w+\b', text.lower())

    # Filter out stopwords
    filtered_words = [w for w in words if w not in STOPWORDS]

    # Count word frequency
    word_counts = Counter(filtered_words)

    # Take the top N words as "key points"
    most_common_words = word_counts.most_common(n)

    return f'The {n} most common words are: {", ".join([word[0] for word in most_common_words])}'