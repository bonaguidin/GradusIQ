# TAMU GPA Calculation Rules
# Source: Texas A&M University Official Academic Policy

## Grade Point Scale

| Letter Grade | Grade Points per Credit Hour |
|-------------|------------------------------|
| A           | 4.00                         |
| B           | 3.00                         |
| C           | 2.00                         |
| D           | 1.00                         |
| F           | 0.00                         |
| U           | 0.00 (undergraduate only)    |

TAMU does not use +/- modifiers in GPA calculation.
When a Canvas current_grade contains a modifier (B+, A-, C+, etc.),
strip the modifier and use the base letter grade only:
  A- → A = 4.00
  B+ → B = 3.00
  B- → B = 3.00
  C+ → C = 2.00
  C- → C = 2.00

Grades of S, W, Q, and NG are excluded from GPA calculation entirely.

## Formula

  GPA = Total Grade Points Earned / Total Credit Hours Attempted

Grade points earned for one course:
  grade_points = grade_point_value × credit_hours

IMPORTANT: Do NOT average semester GPAs and divide by number of
semesters. Always divide cumulative grade points by cumulative
attempted hours.

## Standard Credit Hours by Course (TAMU)

| Course Code | Course Name                        | Credit Hours |
|-------------|-------------------------------------|-------------|
| ENGR 102    | Engineering Lab I: Computation      | 2           |
| MATH 151    | Engineering Mathematics I           | 4           |
| MATH 152    | Engineering Mathematics II          | 4           |
| MATH 251    | Engineering Mathematics III         | 3           |
| CHEM 107    | Gen Chemistry for Engr Students     | 3           |
| CHEM 117    | Gen Chemistry for Engr Students Lab | 1           |
| CHEM 227    | Organic Chemistry I                 | 3           |
| CHEM 237    | Organic Chemistry I Laboratory      | 1           |
| KINE 199    | Health and Physical Fitness         | 1           |
| ENGL 104    | Composition and Rhetoric            | 3           |
| POLS 206    | American National Government        | 3           |
| HIST 105    | History of the United States        | 3           |
| STAT 201    | Elementary Statistical Methods      | 3           |
| PHYS 201    | College Physics I                   | 3           |
| BIOL 213    | Molecular Cell Biology              | 3           |
| AERO 201    | Introduction to Flight              | 3           |
| AERO 211    | Aerospace Engineering Mechanics     | 3           |
| AERO 212    | Introduction to Aerothermodynamics  | 3           |
| AERO 221    | Analytical Methods for AERO Engr    | 3           |
| BUSN 101    | Freshman Business Initiative        | 3           |
| ACCT 229    | Foundations of Accounting I         | 3           |
| MATH 140    | Math for Business & Social Sciences | 3           |
| PBSI 209    | Psychology of Culture and Diversity | 3           |
| PBSI 211    | Stereotyping, Prejudice & Discrim.  | 3           |

## Example Calculation — Jordan Reyes (Spring 2026)

Ethan Brooks was previously the worked example here; he was converted to an
SMU Computer Science student (planning-docs/degree-planner-spec.md §8.4) and
no longer has a TAMU transcript, so this example uses Jordan Reyes's real
course_records instead.

| Course   | Canvas Grade | Base Grade | Pts | Cr Hrs | Weighted |
|----------|-------------|-----------|-----|--------|---------|
| BUSN 101 | A-          | A         | 4.0 | 3      | 12.0    |
| ACCT 229 | B           | B         | 3.0 | 3      | 9.0     |
| MATH 140 | C+          | C         | 2.0 | 3      | 6.0     |
| ENGL 104 | B+          | B         | 3.0 | 3      | 9.0     |
| POLS 206 | B           | B         | 3.0 | 3      | 9.0     |

Total grade points: 45.0
Total credit hours: 15
GPA = 45.0 / 15 = **3.00**

## Rules for AI Features

1. Pull current_grade from enrollments[].grades.current_grade.
2. Strip any +/- modifier — use the base letter only.
3. Look up grade points from the table above.
4. Multiply grade points by credit hours from the table above.
5. Exclude any course where current_grade is null, S, W, Q, or NG.
6. Divide total weighted grade points by total attempted credit hours.
7. Round final GPA to 2 decimal places.
8. Use gpa_current on the student record as the pre-computed source
   of truth. Recalculate only when new grades are available.

When explaining GPA to a student, use plain language:
"Your GPA is the total grade points you've earned — each course's
grade multiplied by its credit hours — divided by the total credit
hours you've attempted. A 4-credit math course affects your GPA
more than a 1-credit lab."

## Data Gap Note

Credit hours are not yet stored on course records in the student
JSON schema. Use the reference table above until a credit_hours
field is added to the courses array.
