/**
 * Article Viewer
 * Loads extracted QTI assessment JSON (organized by units) and renders articles + questions.
 */

const GRADES = [3, 4, 5, 6, 7, 8];
const dataCache = {};
let currentGrade = null;
let flatAssessments = []; // flattened list for current grade
let allArticleItems = []; // DOM elements for search filtering

// DOM references
const gradeTabs = document.getElementById('gradeTabs');
const articleList = document.getElementById('articleList');
const searchInput = document.getElementById('searchInput');
const content = document.getElementById('content');
const contentPlaceholder = document.getElementById('contentPlaceholder');
const articleView = document.getElementById('articleView');
const articleTitle = document.getElementById('articleTitle');
const articleMeta = document.getElementById('articleMeta');
const passageContainer = document.getElementById('passageContainer');
const passageContent = document.getElementById('passageContent');
const questionsContainer = document.getElementById('questionsContainer');
const questionsList = document.getElementById('questionsList');

// Initialize grade tabs
function initTabs() {
    GRADES.forEach(grade => {
        const btn = document.createElement('button');
        btn.className = 'grade-tab';
        btn.textContent = `Grade ${grade}`;
        btn.dataset.grade = grade;
        btn.addEventListener('click', () => selectGrade(grade));
        gradeTabs.appendChild(btn);
    });
}

// Load grade data
async function loadGrade(grade) {
    if (dataCache[grade]) return dataCache[grade];
    const resp = await fetch(`data/grade${grade}.json`);
    if (!resp.ok) throw new Error(`Failed to load grade ${grade} data`);
    const data = await resp.json();
    dataCache[grade] = data;
    return data;
}

// Select a grade
async function selectGrade(grade) {
    document.querySelectorAll('.grade-tab').forEach(tab => {
        tab.classList.toggle('active', parseInt(tab.dataset.grade) === grade);
    });

    currentGrade = grade;
    flatAssessments = [];
    articleList.innerHTML = '<div class="loading">Loading</div>';
    hideArticle();

    try {
        const data = await loadGrade(grade);
        renderArticleList(data);
    } catch (e) {
        articleList.innerHTML = `<p class="placeholder-text">Could not load Grade ${grade} data. Make sure data/grade${grade}.json exists.</p>`;
    }
}

// Render article list in sidebar, grouped by unit
function renderArticleList(data) {
    allArticleItems = [];
    flatAssessments = [];
    articleList.innerHTML = '';

    const units = data.units || [];

    units.forEach(unit => {
        const assessments = unit.assessments || [];
        if (assessments.length === 0) return;

        // Unit header
        const unitHeader = document.createElement('div');
        unitHeader.className = 'unit-header';
        unitHeader.textContent = unit.title;
        articleList.appendChild(unitHeader);

        assessments.forEach(assessment => {
            if (assessment.error) return;

            const index = flatAssessments.length;
            flatAssessments.push(assessment);

            const title = assessment.syllabus_metadata?.title || assessment.title || assessment.identifier;
            const itemCount = countItems(assessment);
            const xp = assessment.syllabus_metadata?.xp;

            const div = document.createElement('div');
            div.className = 'article-item';
            div.innerHTML = `
                <div>${escapeHtml(title)}</div>
                <div class="article-item-meta">${itemCount} question${itemCount !== 1 ? 's' : ''}${xp ? ' · ' + xp + ' XP' : ''}</div>
            `;
            div.addEventListener('click', () => selectArticle(index));
            articleList.appendChild(div);
            allArticleItems.push({
                el: div,
                unitEl: unitHeader,
                title: title.toLowerCase(),
                unitTitle: unit.title.toLowerCase(),
                index
            });
        });
    });

    if (flatAssessments.length === 0) {
        articleList.innerHTML = '<p class="placeholder-text">No articles found for this grade.</p>';
    }
}

// Count total items in an assessment
function countItems(assessment) {
    let count = 0;
    for (const part of (assessment.test_parts || [])) {
        for (const section of (part.sections || [])) {
            count += (section.items || []).length;
        }
    }
    return count;
}

// Search filter
searchInput.addEventListener('input', () => {
    const query = searchInput.value.toLowerCase().trim();
    // Track which unit headers have visible children
    const unitHeaderVisibility = new Map();

    allArticleItems.forEach(({ el, unitEl, title, unitTitle }) => {
        const match = !query || title.includes(query) || unitTitle.includes(query);
        el.style.display = match ? '' : 'none';
        if (match) unitHeaderVisibility.set(unitEl, true);
    });

    // Hide unit headers with no visible children
    document.querySelectorAll('.unit-header').forEach(header => {
        header.style.display = unitHeaderVisibility.has(header) ? '' : 'none';
    });
});

// Select an article
function selectArticle(index) {
    allArticleItems.forEach(({ el, index: i }) => {
        el.classList.toggle('active', i === index);
    });

    const assessment = flatAssessments[index];
    renderArticle(assessment);
}

// Hide article view
function hideArticle() {
    articleView.style.display = 'none';
    contentPlaceholder.style.display = '';
}

// Render article content
function renderArticle(assessment) {
    contentPlaceholder.style.display = 'none';
    articleView.style.display = '';

    // Title
    const title = assessment.syllabus_metadata?.title || assessment.title || assessment.identifier;
    articleTitle.textContent = title;

    // Meta
    const metaParts = [];
    if (assessment.identifier) {
        metaParts.push(`<span class="meta-tag">${escapeHtml(assessment.identifier)}</span>`);
    }
    const xp = assessment.syllabus_metadata?.xp;
    if (xp) {
        metaParts.push(`<span class="meta-tag">${xp} XP</span>`);
    }
    const lexile = assessment.metadata?.lexileLevel;
    if (lexile) {
        metaParts.push(`<span class="meta-tag">Lexile ${escapeHtml(lexile)}</span>`);
    }
    const readingGrade = assessment.metadata?.measuredReadingGrade;
    if (readingGrade) {
        metaParts.push(`<span class="meta-tag">Reading Grade ${escapeHtml(readingGrade)}</span>`);
    }
    articleMeta.innerHTML = metaParts.join('');

    // Collect all items grouped by stimulus section
    const sections = [];

    for (const part of (assessment.test_parts || [])) {
        for (const section of (part.sections || [])) {
            for (const item of (section.items || [])) {
                const stimId = item.stimulus?.identifier || null;
                let sec = sections.find(s => s.stimulusId === stimId);
                if (!sec) {
                    sec = {
                        stimulusId: stimId,
                        stimulus: item.stimulus,
                        sectionTitle: section.title,
                        items: []
                    };
                    sections.push(sec);
                }
                sec.items.push({ ...item, _sectionTitle: section.title || '' });
            }
        }
    }

    // Hide the static passage container, we render inline
    passageContainer.style.display = 'none';
    passageContent.innerHTML = '';

    questionsList.innerHTML = '';
    const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    let questionNum = 0;

    sections.forEach((sec) => {
        if (sec.stimulus && sec.stimulus.content_html) {
            const passageDiv = document.createElement('div');
            passageDiv.className = 'passage-container';
            const stimTitle = sec.stimulus.title || 'Reading Passage';
            passageDiv.innerHTML = `
                <h3 class="section-heading">${escapeHtml(stimTitle)}</h3>
                <div class="passage">${sec.stimulus.content_html}</div>
            `;
            questionsList.appendChild(passageDiv);
        }

        sec.items.forEach((item) => {
            questionNum++;
            const card = document.createElement('div');
            card.className = 'question-card';

            let choicesHtml = '';
            if (item.interaction_type === 'choice' && item.choices && item.choices.length) {
                choicesHtml = '<ul class="choices-list">' + item.choices.map((choice, ci) => {
                    const isCorrect = choice.is_correct;
                    const feedbackHtml = choice.feedback
                        ? `<span class="choice-feedback">${escapeHtml(choice.feedback)}</span>`
                        : '';
                    return `
                        <li class="choice ${isCorrect ? 'correct' : ''}">
                            <span class="choice-letter">${letters[ci] || ci + 1}</span>
                            <span class="choice-content">
                                <span class="choice-text">${escapeHtml(choice.text)}</span>
                                ${feedbackHtml}
                            </span>
                        </li>
                    `;
                }).join('') + '</ul>';
            } else if (item.interaction_type === 'text_entry' || item.interaction_type === 'extended_text') {
                const answers = (item.correct_answers || []).join(', ');
                if (answers) {
                    choicesHtml = `
                        <div class="correct-answer-box">
                            <div class="correct-answer-label">Correct Answer</div>
                            ${escapeHtml(answers)}
                        </div>
                    `;
                }
            }

            const typeLabel = item.interaction_type === 'choice' ? 'Multiple Choice'
                : item.interaction_type === 'text_entry' ? 'Text Entry'
                : item.interaction_type === 'extended_text' ? 'Extended Response'
                : '';

            // Determine guiding vs quiz from section title
            const sectionTag = item._sectionTitle.toLowerCase().startsWith('guiding') ? 'Guiding'
                : item._sectionTitle.toLowerCase() === 'quiz' ? 'Quiz'
                : '';

            // Build standards tag HTML
            const meta = item.metadata || {};
            const ccssValues = meta.ccss || meta.CCSS || [];
            const ccssArr = Array.isArray(ccssValues) ? ccssValues : (ccssValues ? [ccssValues] : []);
            const dok = meta.dok || meta.DOK;
            const difficulty = meta.difficulty;

            let standardsHtml = '';
            if (ccssArr.length || dok || difficulty) {
                const tags = [];
                ccssArr.forEach(s => tags.push(`<span class="standard-tag">${escapeHtml(String(s))}</span>`));
                if (dok) tags.push(`<span class="standard-tag dok">DOK ${escapeHtml(String(dok))}</span>`);
                if (difficulty) tags.push(`<span class="standard-tag difficulty">${escapeHtml(String(difficulty))}</span>`);
                standardsHtml = `<div class="standards-box">${tags.join('')}</div>`;
            }

            card.innerHTML = `
                <div class="question-number">${sectionTag ? sectionTag + ' — ' : ''}Question ${questionNum}${typeLabel ? ' — ' + typeLabel : ''}</div>
                ${standardsHtml}
                <div class="question-prompt">${escapeHtml(item.prompt || 'No prompt available')}</div>
                ${choicesHtml}
            `;

            questionsList.appendChild(card);
        });
    });

    if (questionNum === 0) {
        questionsList.innerHTML = '<p class="placeholder-text">No questions found for this article.</p>';
    }

    content.scrollTop = 0;
}

// Utility: escape HTML
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Handle URL hash for deep linking (e.g., #grade=5)
function handleHash() {
    const hash = window.location.hash;
    const match = hash.match(/grade=(\d+)/);
    if (match) {
        const grade = parseInt(match[1]);
        if (GRADES.includes(grade)) {
            selectGrade(grade);
            return true;
        }
    }
    return false;
}

// Initialize
initTabs();
handleHash();
