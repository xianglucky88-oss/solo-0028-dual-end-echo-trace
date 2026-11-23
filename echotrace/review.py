from .capture import capture_regions, sample_support, supported_visibility
from .closure_review import closure_quality, competition_groups, polarity_conflicts, revisit_coverage
from .contract import num


def analyze_review(review, model, facts, outputs):
    limit = num(review.get('max_sample_gap_ns', 120), '采样连续性时差', .001, 1e9)
    gaps = capture_regions(model, limit)
    support = sample_support(model, facts, limit)
    visibility = supported_visibility(outputs['visibility'], gaps, outputs['pair'])
    return dict(capture_gaps=gaps, capture_view=visibility, peak_support=support,
                competition=competition_groups(outputs['pending']), polarity_review=polarity_conflicts(model, outputs),
                closure_quality=closure_quality(outputs['pair'], support),
                revisit_coverage=revisit_coverage(outputs['revisit'], visibility, model['length']))
