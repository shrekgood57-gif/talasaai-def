# TalaSaAI Test Data Additions (Instructor Demo Ready)

This document explains the new mock test data added for system flow demonstration.

## Goal
Provide clearer end-to-end demo data for thesis checking:
- 3 leveled students (Easy, Moderate, Difficult)
- 1 new student who **must take pre-assessment first** (no current difficulty)
- realistic passages and aligned questions for each difficulty level
- weekly progress records for leveled students

---

## File Updated
- `client_assessment_helpers.js`

---

## 1) New Students Added

Added to `MOCK.students`:

1. **s12 – Ella Mendoza**
   - Grade/Section: Grade 7, Jasmin
   - `classLevel`: `EASY`
   - `preScore`: 86

2. **s13 – Miguel Ramos**
   - Grade/Section: Grade 7, Jasmin
   - `classLevel`: `MODERATE`
   - `preScore`: 67

3. **s14 – Sofia Bautista**
   - Grade/Section: Grade 7, Jasmin
   - `classLevel`: `HARD`
   - `preScore`: 51

4. **s15 – Nico Villareal** (pre-assessment flow student)
   - Grade/Section: Grade 7, Jasmin
   - `classLevel`: `""` (empty, no difficulty yet)
   - `preScore`: 0
   - `preAssessmentCompleted`: `false`

### Why s15 is correct for pre-assessment flow
Your code includes gate logic in `enforceStudentPreAssessmentGate()` checking `preAssessmentCompleted`.
With `preAssessmentCompleted:false`, this student is forced to complete pre-assessment first.

---

## 2) New Passages Added

Added to `MOCK.passages`:

1. **p7 – "Planting a School Garden"**  
   - Label: `EASY`
   - Genre: Procedural
   - Classroom-friendly and simple sequence/process comprehension

2. **p8 – "Jeepney Modernization Debate"**  
   - Label: `MODERATE`
   - Genre: Argumentative
   - Balanced viewpoint text, good for inference/comparison

3. **p9 – "How Vaccines Build Community Protection"**  
   - Label: `HARD`
   - Genre: Expository
   - Technical concepts and deeper comprehension load

---

## 3) New Question Sets Added

Added to `MOCK.questions`:

- `p7`: 3 multiple-choice items aligned to easy comprehension
- `p8`: 3 multiple-choice items aligned to moderate analysis
- `p9`: 3 multiple-choice items aligned to hard conceptual understanding

Also added in `MOCK.shortAnswer`:
- `p9`: `"How does herd immunity help protect people who cannot be vaccinated?"`

---

## 4) Weekly Progress Added

Added to `MOCK.weeklyProgress`:

- `s12`: EASY progression with step-up toward MODERATE
- `s13`: MODERATE progression with potential step-up toward HARD
- `s14`: HARD to MODERATE stabilization path
- `s15`: empty (`[]`) by design (pre-assessment pending)

---

## 5) Data Design Notes

- Used existing class-level conventions:
  - `EASY`
  - `MODERATE`
  - `HARD`  
- Used existing recommendation style:
  - `Maintain`
  - `Step UP to ...`
  - `Step DOWN to ...`
- Ensured new records are consistent with existing schema and helper functions in `client_assessment_helpers.js`.

---

## 6) Quick Verification Checklist

1. Open teacher dashboard/students pages:
   - confirm new students `s12`, `s13`, `s14`, `s15` are visible in system data-driven views.
2. Check passages list:
   - confirm `p7`, `p8`, `p9` are present.
3. Check question rendering:
   - confirm each new passage has 3 questions.
4. Check pre-assessment student behavior:
   - login/open flow for `s15` should redirect/require pre-assessment due to `preAssessmentCompleted:false`.
5. Check recommendations/progress areas:
   - `s12/s13/s14` have weekly history;
   - `s15` remains unclassified until pre-assessment.

---

## 7) Login Accounts for the 4 New Students

These are seeded in backend `app.py` (`SEED_STUDENTS`) and can be used directly in the login page:

- **Ella Mendoza (Easy)**  
  - Email: `ella.mendoza@pnhs.edu`  
  - Password: `password123`

- **Miguel Ramos (Moderate)**  
  - Email: `miguel.ramos@pnhs.edu`  
  - Password: `password123`

- **Sofia Bautista (Difficult/Hard)**  
  - Email: `sofia.bautista@pnhs.edu`  
  - Password: `password123`

- **Nico Villareal (Pre-assessment first)**  
  - Email: `nico.villareal@pnhs.edu`  
  - Password: `password123`  
  - Note: starts with pre-assessment incomplete so flow can demonstrate pre-assessment gating.

---

## 8) Passage Length Upgrade for Believability

In backend seed data (`app.py` → `SEED_PASSAGES`), the assessment passages were extended to be longer and more realistic for demo use:

- `p7` **The School Garden**: expanded with clearer process, observations, and outcomes.
- `p8` **A Day at the Library**: expanded into a fuller narrative with task context and study details.
- `p9` **Why We Wash Hands**: expanded into a fuller explanatory passage with practical hygiene rationale.

This improves reading realism for instructor demonstration while preserving level-appropriate comprehension.

---

## Summary

You now have:
- **4 additional student accounts with working login credentials**
- **3 additional properly-leveled passages**
- **longer and more believable seeded assessment passages**
- **aligned question sets + short-answer prompt**
- **weekly progress trajectories** for leveled students
- **one explicit pre-assessment-required student** for initial flow demonstration

## Live Database Stagnant-Student Seed

To add a student to the live MySQL database and make the teacher report display a
stagnant-learning alert, run this from the application repository in the Railway
console:

```powershell
python scripts\seed_stagnant_student.py --email stagnant.demo@example.com --name "Stagnant Demo Student"
```

The script prompts for and confirms a password without displaying it. It uses the
database connection settings already configured for the app, creates a new active
student account, and inserts two quiz attempts using published passages assigned
to the student's class level. By default the earlier score is 60% and the latest
is 55%. You can change those with `--previous-score` and `--latest-score`, provided
the latest score is not higher.

The script uses the current program week and the preceding week. If the program
is in Week 1, it seeds Weeks 1 and 2 so there are two scores to compare. It refuses
to reuse an existing email, and rolls back all inserts if a required weekly
assignment is missing.
