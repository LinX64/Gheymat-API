"""
Enhanced Sentiment Analysis for Currency Predictions
Analyzes news across multiple categories with weighted impact scoring
"""

import json
from typing import Dict, List, Any
from collections import defaultdict


class EnhancedSentimentAnalyzer:
    """Advanced sentiment analysis with category-specific weighting"""

    # Enhanced keyword lists with weights
    POSITIVE_KEYWORDS = {
        # Economic positive
        'growth': 1.0, 'increase': 0.8, 'rise': 0.8, 'surge': 1.0, 'gain': 0.8,
        'bull': 1.0, 'rally': 1.0, 'strong': 0.9, 'boost': 0.9, 'recovery': 1.0,
        'positive': 0.7, 'optimistic': 0.8, 'improve': 0.8, 'expansion': 0.9,
        'prosperity': 1.0, 'strengthen': 0.9, 'advance': 0.8, 'upturn': 1.0,

        # Policy positive
        'agreement': 0.9, 'deal': 0.8, 'cooperation': 0.9, 'stability': 1.0,
        'peace': 1.0, 'resolution': 0.9, 'diplomatic': 0.8, 'negotiate': 0.7,
        'partnership': 0.8, 'trade deal': 1.0, 'export': 0.7, 'investment': 0.9
    }

    NEGATIVE_KEYWORDS = {
        # Economic negative
        'fall': 0.8, 'decline': 0.8, 'drop': 0.8, 'crash': 1.2, 'bear': 1.0,
        'weak': 0.8, 'crisis': 1.2, 'recession': 1.2, 'negative': 0.7,
        'pessimistic': 0.8, 'concern': 0.7, 'worry': 0.7, 'risk': 0.8,
        'volatility': 0.6, 'uncertainty': 0.8, 'downturn': 1.0, 'slump': 1.0,

        # Geopolitical negative
        'war': 1.5, 'conflict': 1.3, 'tension': 1.0, 'sanctions': 1.5,
        'embargo': 1.5, 'attack': 1.3, 'strike': 1.0, 'threat': 1.0,
        'crisis': 1.2, 'instability': 1.1, 'protest': 0.8, 'unrest': 1.0,
        'disruption': 1.0, 'blockade': 1.3
    }

    # Iran-specific keywords
    IRAN_POSITIVE_KEYWORDS = {
        'nuclear deal': 1.5, 'jcpoa': 1.5, 'sanctions relief': 2.0,
        'oil export': 1.0, 'trade agreement': 1.2, 'diplomatic': 0.8,
        'normalize': 1.0, 'lift sanctions': 2.0, 'trade increase': 1.0
    }

    IRAN_NEGATIVE_KEYWORDS = {
        'sanctions': 2.0, 'embargo': 2.0, 'nuclear program': 1.0,
        'tensions': 1.5, 'restrictions': 1.5, 'ban': 1.5,
        'freeze assets': 2.0, 'isolation': 1.8, 'strike': 1.5
    }

    # Category weights for impact on currency predictions
    CATEGORY_WEIGHTS = {
        'forex_economic': 1.0,      # Direct impact
        'iran_specific': 1.5,       # High impact on Iranian Rial
        'geopolitical_war': 1.3,    # High impact due to uncertainty
        'uae_regional': 0.9,        # Moderate impact (AED correlation)
        'general': 0.5              # Lower impact
    }

    @staticmethod
    def analyze_article_sentiment(article: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze sentiment of a single article with enhanced scoring"""
        text = f"{article.get('title', '')} {article.get('description', '')} {article.get('content', '')}".lower()
        category = article.get('category', 'general')

        positive_score = 0.0
        negative_score = 0.0
        iran_positive_score = 0.0
        iran_negative_score = 0.0

        # Check general keywords
        for keyword, weight in EnhancedSentimentAnalyzer.POSITIVE_KEYWORDS.items():
            count = text.count(keyword.lower())
            positive_score += count * weight

        for keyword, weight in EnhancedSentimentAnalyzer.NEGATIVE_KEYWORDS.items():
            count = text.count(keyword.lower())
            negative_score += count * weight

        # Check Iran-specific keywords
        for keyword, weight in EnhancedSentimentAnalyzer.IRAN_POSITIVE_KEYWORDS.items():
            count = text.count(keyword.lower())
            iran_positive_score += count * weight

        for keyword, weight in EnhancedSentimentAnalyzer.IRAN_NEGATIVE_KEYWORDS.items():
            count = text.count(keyword.lower())
            iran_negative_score += count * weight

        # Combine scores with Iran-specific boost
        total_positive = positive_score + iran_positive_score
        total_negative = negative_score + iran_negative_score

        # Calculate sentiment score (-1 to 1)
        total_indicators = total_positive + total_negative
        if total_indicators == 0:
            sentiment_score = 0.0
        else:
            sentiment_score = (total_positive - total_negative) / total_indicators

        # Apply category weight
        category_weight = EnhancedSentimentAnalyzer.CATEGORY_WEIGHTS.get(category, 0.5)
        weighted_score = sentiment_score * category_weight

        return {
            'sentiment_score': sentiment_score,
            'weighted_score': weighted_score,
            'positive_indicators': total_positive,
            'negative_indicators': total_negative,
            'category': category,
            'category_weight': category_weight
        }

    @staticmethod
    def analyze_enhanced_news(news_file: str = 'api/news.json') -> Dict[str, Any]:
        """Analyze enhanced news with category-specific sentiment"""
        try:
            with open(news_file, 'r') as f:
                news_data = json.load(f)

            if not news_data:
                return {
                    'sentiment': 'NEUTRAL',
                    'score': 0.0,
                    'confidence': 0.5,
                    'articlesAnalyzed': 0
                }

            # Analyze each article
            article_sentiments = []
            category_sentiments = defaultdict(list)

            for article in news_data:
                sentiment_result = EnhancedSentimentAnalyzer.analyze_article_sentiment(article)
                article_sentiments.append(sentiment_result)

                category = sentiment_result['category']
                category_sentiments[category].append(sentiment_result['weighted_score'])

            # Calculate overall sentiment (weighted average)
            if article_sentiments:
                overall_score = sum(s['weighted_score'] for s in article_sentiments) / len(article_sentiments)
            else:
                overall_score = 0.0

            # Calculate category-specific sentiments
            category_scores = {}
            for category, scores in category_sentiments.items():
                if scores:
                    category_scores[category] = {
                        'score': sum(scores) / len(scores),
                        'articles': len(scores)
                    }

            # Determine overall sentiment
            if overall_score > 0.2:
                sentiment = 'POSITIVE'
            elif overall_score < -0.2:
                sentiment = 'NEGATIVE'
            else:
                sentiment = 'NEUTRAL'

            # Calculate confidence based on number of articles and consistency
            article_count_factor = min(1.0, len(news_data) / 50.0)
            score_consistency = 1.0 - min(1.0, abs(overall_score) * 0.3)  # More extreme = more confident
            confidence = min(0.95, 0.6 + article_count_factor * 0.2 + score_consistency * 0.2)

            # Calculate impact factor for predictions
            # Higher absolute score = more impact on predictions
            impact_factor = min(1.0, abs(overall_score) * 2.0)

            return {
                'sentiment': sentiment,
                'score': round(overall_score, 3),
                'confidence': round(confidence, 3),
                'impactFactor': round(impact_factor, 3),
                'articlesAnalyzed': len(news_data),
                'categoryBreakdown': category_scores,
                'totalPositiveIndicators': sum(s['positive_indicators'] for s in article_sentiments),
                'totalNegativeIndicators': sum(s['negative_indicators'] for s in article_sentiments)
            }

        except FileNotFoundError:
            print(f"News file not found: {news_file}")
            return {
                'sentiment': 'NEUTRAL',
                'score': 0.0,
                'confidence': 0.5,
                'articlesAnalyzed': 0,
                'error': 'News file not found'
            }
        except Exception as e:
            print(f"Error analyzing news: {e}")
            return {
                'sentiment': 'NEUTRAL',
                'score': 0.0,
                'confidence': 0.5,
                'articlesAnalyzed': 0,
                'error': str(e)
            }

    @staticmethod
    def calculate_economic_indicators_sentiment(indicators: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate sentiment from economic indicators"""
        sentiment_score = 0.0
        factors = []

        # Oil prices impact (higher oil = potentially negative for Iran if sanctions prevent export)
        oil_data = indicators.get('oil', {})
        if 'wti' in oil_data:
            wti = oil_data.get('wti', 75)
            if wti > 90:
                sentiment_score -= 0.2  # High oil but can't export = negative
                factors.append('high_oil_sanctions')
            elif wti > 80:
                sentiment_score -= 0.1

        # Gold prices impact (higher gold = economic uncertainty = flight to safety)
        gold_data = indicators.get('gold', {})
        if 'pricePerOunce' in gold_data:
            gold_price = gold_data.get('pricePerOunce', 2000)
            if gold_price > 2100:
                sentiment_score -= 0.15  # High gold = uncertainty
                factors.append('high_gold_uncertainty')
            elif gold_price < 1900:
                sentiment_score += 0.1  # Low gold = stability

        # Sanctions impact (direct negative)
        sanctions_data = indicators.get('sanctions', {})
        sanctions_level = sanctions_data.get('iran_sanctions_level', 'medium')
        impact_score = sanctions_data.get('impact_score', 0.5)

        if sanctions_level == 'high':
            sentiment_score -= 0.4
            factors.append('high_sanctions')
        elif sanctions_level == 'medium':
            sentiment_score -= 0.2
            factors.append('medium_sanctions')

        # Normalize to -1 to 1 range
        sentiment_score = max(-1.0, min(1.0, sentiment_score))

        return {
            'score': round(sentiment_score, 3),
            'factors': factors,
            'impact': 'negative' if sentiment_score < -0.1 else ('positive' if sentiment_score > 0.1 else 'neutral')
        }

    @staticmethod
    def get_combined_sentiment(news_file: str = 'api/news.json',
                               economic_indicators_file: str = 'api/economic_indicators.json') -> Dict[str, Any]:
        """Get combined sentiment from news and economic indicators"""

        # Get news sentiment
        news_sentiment = EnhancedSentimentAnalyzer.analyze_enhanced_news(news_file)

        # Get economic indicators sentiment
        try:
            with open(economic_indicators_file, 'r') as f:
                indicators = json.load(f)
            economic_sentiment = EnhancedSentimentAnalyzer.calculate_economic_indicators_sentiment(indicators)
        except:
            economic_sentiment = {'score': 0.0, 'factors': [], 'impact': 'neutral'}

        # Combine sentiments (70% news, 30% economic indicators)
        combined_score = news_sentiment['score'] * 0.7 + economic_sentiment['score'] * 0.3

        # Overall sentiment
        if combined_score > 0.2:
            overall_sentiment = 'POSITIVE'
        elif combined_score < -0.2:
            overall_sentiment = 'NEGATIVE'
        else:
            overall_sentiment = 'NEUTRAL'

        return {
            'overallSentiment': overall_sentiment,
            'combinedScore': round(combined_score, 3),
            'newsSentiment': news_sentiment,
            'economicSentiment': economic_sentiment,
            'confidence': news_sentiment.get('confidence', 0.5)
        }


if __name__ == '__main__':
    # Test
    sentiment = EnhancedSentimentAnalyzer.get_combined_sentiment()
    print(json.dumps(sentiment, indent=2))
