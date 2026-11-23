from .capture import capture_regions, sample_support, supported_visibility
from .closure_review import closure_quality, competition_groups, polarity_conflicts, revisit_coverage


def analyze_review(model, facts, outputs):
    limit = model['sample_gap_limit']
    gaps = capture_regions(model, limit)
    support = sample_support(model, facts, limit)
    visibility = supported_visibility(outputs['visibility'], gaps, outputs['pair'])
    return dict(capture_gaps=gaps, capture_view=visibility, peak_support=support,
                competition=competition_groups(outputs['pending']), polarity_review=polarity_conflicts(model, outputs),
                closure_quality=closure_quality(outputs['pair'], support),
                revisit_coverage=revisit_coverage(outputs['revisit'], visibility, model['length']))
