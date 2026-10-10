"""
Keyword-based skill extraction from job description text.

This is intentionally simple: a maintained list of skill names, matched
against the description with word-boundary regexes. It will miss skills
phrased unusually and won't catch anything not on the list -- the tradeoff
for being free and fully predictable (no API calls, no per-posting cost).

Maintain SKILLS below to match what actually shows up in postings you care
about. It's grouped loosely by category for readability; matching doesn't
care about the grouping.
"""

import re

SKILLS = [
    # Languages
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust",
    "Ruby", "PHP", "Swift", "Kotlin", "Scala", "SQL", "R", "MATLAB",

    # Web / frontend
    "React", "Angular", "Vue", "Next.js", "Node.js", "HTML", "CSS",
    "REST API", "GraphQL", "Redux",

    # Data / ML
    "Machine Learning", "Deep Learning", "Natural Language Processing",
    "Computer Vision", "Pandas", "NumPy", "TensorFlow", "PyTorch",
    "Scikit-learn", "Data Analysis", "Data Visualization", "ETL",
    "Apache Spark", "Hadoop", "Tableau", "Power BI",

    # Cloud / infra
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "CI/CD",
    "Jenkins", "Linux", "Microservices", "Serverless",

    # Databases
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "DynamoDB",

    # Product / project management
    "Agile", "Scrum", "Kanban", "JIRA", "Product Management",
    "Project Management", "Roadmapping", "Stakeholder Management",

    # Design
    "Figma", "UI/UX", "User Research", "Wireframing",

    # Soft / general professional
    "Cross-functional Collaboration", "Communication", "Leadership",
    "Mentoring", "Technical Writing", "Public Speaking",

    # Business / analytics
    "Excel", "Salesforce", "SAP", "Financial Modeling", "A/B Testing",
    "SEO", "Google Analytics",
]

_PATTERNS = {
    skill: re.compile(r"\b" + re.escape(skill).replace(r"\ ", r"[\s\-]*") + r"\b", re.IGNORECASE)
    for skill in SKILLS
}


def extract_skills(text: str) -> list[str]:
    """Returns the canonical skill names (from SKILLS) found in text."""
    if not text:
        return []
    found = [skill for skill, pattern in _PATTERNS.items() if pattern.search(text)]
    return sorted(found)
