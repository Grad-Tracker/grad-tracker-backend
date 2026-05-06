# Speaker Notes For Slides 12 And 15

Author: CJ Shane

These are presentation notes, not the canonical database documentation. Use `docs/database-schema-and-data-flow.md` for current schema details.

## Slide 12 - CJ Shane: Data Scraping, Database Architecture & Planner Algorithm

For my part of the project, I focused mostly on the backend data foundation and the planner logic that depends on it.

The first major piece was scraping the UW-Parkside catalog. We loaded 2,298 courses across 111 subjects into Supabase, including course details, offerings, prerequisites, and catalog structure. That gave the app real academic data instead of sample or mock data.

After that, I worked on connecting the planner to the actual database. A big goal was to stop relying on hardcoded requirement data and make the frontend read from live Supabase views. I helped create database views and supporting indexes so the frontend could query clean, consistent data without duplicating complicated joins everywhere.

I also worked on the auto plan generator. That algorithm takes real program requirements, Gen-Ed requirements, completed courses, and credit totals, then builds a multi-semester plan. One important fix was making sure completed courses were excluded from future plans and that credit totals matched between the summary and requirement blocks.

Overall, this work made the app more realistic: the planner is now driven by catalog data, program requirements, and database views instead of static demo data.

## Slide 15 - Infrastructure: Database Footprint

This slide shows the scale of the database work behind the app.

On the catalog side, we have 2,298 scraped courses and 3,113 course offering records. For programs, the database includes 159 total programs, split across majors, minors, certificates, and graduate programs.

The requirement layer is where a lot of the complexity lives. We have 834 requirement blocks, 3,870 requirement-course entries, and structured requirement trees. That is what lets the planner understand what a student actually needs for a program.

We also parsed structured prerequisite logic, with 1,737 course prerequisite sets and 4,694 course prerequisite tree nodes. Program requirements have their own tree layer as well, with 4,646 program requirement nodes. That matters because requirements are not always simple one-course rules.

The main point is that the database is not just storing raw data. It is organizing catalog, requirement, prerequisite, cross-listing, and Gen-Ed data into a structure the frontend can use efficiently.
