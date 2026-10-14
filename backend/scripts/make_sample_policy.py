"""Generate the fictional sample policy PDF used by the live demo.

Real insurers' documents are copyrighted and change every year, so the demo
ships its own plan: "Evergreen Mutual Health - Silver 3000 PPO". It follows the
structure of a real US Evidence of Coverage (numbered sections, a schedule of
benefits, prior authorization rules, exclusions, appeals) so the RAG pipeline
is exercised on realistic text, and the evaluation set (eval/questions.json)
can check answers against known ground truth.

Run:  python scripts/make_sample_policy.py
"""

import json
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
PDF_PATH = OUT_DIR / "evergreen-silver-3000-ppo.pdf"
FACTS_PATH = OUT_DIR / "evergreen-silver-3000-ppo.facts.json"

PLAN_FACTS = {
    "plan_name": "Evergreen Silver 3000 PPO",
    "insurer": "Evergreen Mutual Health (fictional)",
    "plan_type": "PPO",
    "plan_year": "2026",
    "deductible_individual": 3000,
    "deductible_family": 6000,
    "oop_max_individual": 8500,
    "oop_max_family": 17000,
    "coinsurance_in_network_percent": 30,
    "coinsurance_out_of_network_percent": 50,
    "primary_care_copay": 30,
    "specialist_copay": 60,
    "emergency_room_copay": 400,
}

# Each entry: ("major" | "minor" | "p" | "break", text)
CONTENT: list[tuple[str, str]] = [
    ("title", "Evergreen Mutual Health"),
    ("title2", "Silver 3000 PPO - Evidence of Coverage - Plan Year 2026"),
    ("p", "<b>SAMPLE DOCUMENT.</b> This is a fictional health plan created for the \"Am I Covered?\" demo. "
          "Evergreen Mutual Health is not a real insurance company and this is not a real insurance product."),
    ("p", "This Evidence of Coverage explains what the Evergreen Silver 3000 PPO plan covers, what it does not cover, "
          "and what you pay. Read it together with your Summary of Benefits and Coverage. If the two documents "
          "disagree, this Evidence of Coverage controls. Words that start with a capital letter, such as Allowed "
          "Amount or Medically Necessary, are defined in Section 2."),
    ("p", "Questions? Call Evergreen Member Services at 1-800-555-0142, Monday to Friday, 8 a.m. to 8 p.m."),
    ("break", ""),

    ("major", "SECTION 1 - YOUR PLAN AT A GLANCE"),
    ("minor", "1.1 Key Costs"),
    ("p", "Plan year: January 1, 2026 to December 31, 2026."),
    ("p", "Deductible: $3,000 per person and $6,000 per family for In-Network services. $6,000 per person and "
          "$12,000 per family for Out-of-Network services. In-Network and Out-of-Network deductibles are separate."),
    ("p", "Out-of-pocket maximum: $8,500 per person and $17,000 per family for In-Network services. "
          "$17,000 per person and $34,000 per family for Out-of-Network services. Premiums, balance-billed charges "
          "and services this plan does not cover do not count toward the out-of-pocket maximum."),
    ("p", "Coinsurance: after you meet the deductible, you pay 30% of the Allowed Amount for most In-Network "
          "services and 50% of the Allowed Amount for most Out-of-Network services. The plan pays the rest."),
    ("minor", "1.2 Your Network"),
    ("p", "This is a Preferred Provider Organization (PPO) plan. You pay less when you use providers in the "
          "Evergreen Preferred Network. You do not need a referral to see a Specialist. You can find Network "
          "Providers at evergreen-mutual.example/find-a-doctor."),
    ("minor", "1.3 How Cost-Sharing Works"),
    ("p", "For most services you pay the full Allowed Amount until you meet your deductible, then you pay "
          "coinsurance. Services listed with a copay and the words deductible does not apply cost only the copay, "
          "even if you have not met your deductible. Once you reach the out-of-pocket maximum, the plan pays 100% "
          "of covered In-Network services for the rest of the plan year."),
    ("break", ""),

    ("major", "SECTION 2 - DEFINITIONS"),
    ("p", "<b>Allowed Amount:</b> the maximum amount the plan pays for a covered service. Network Providers "
          "accept the Allowed Amount as payment in full. Out-of-Network providers may bill you the difference "
          "(balance billing), except where federal law protects you."),
    ("p", "<b>Emergency Medical Condition:</b> a medical condition with symptoms so severe, including severe "
          "pain, that a prudent layperson with average knowledge of health and medicine would expect that not "
          "getting immediate care would seriously endanger their health."),
    ("p", "<b>Medically Necessary:</b> services that a provider would give to prevent, diagnose or treat an "
          "illness, injury, disease or its symptoms, that meet accepted standards of medicine, and that are not "
          "mainly for the convenience of the patient or provider."),
    ("p", "<b>Network Provider:</b> a doctor, hospital or other provider that has a contract with Evergreen to "
          "provide services to members at negotiated rates."),
    ("p", "<b>Prior Authorization:</b> approval from Evergreen, before you receive a service, that the service "
          "is Medically Necessary. Section 4 lists the services that need it."),
    ("p", "<b>Specialist:</b> a physician who focuses on a specific area of medicine, such as a cardiologist, "
          "dermatologist or orthopedic surgeon."),
    ("p", "<b>Urgent Care:</b> care for an illness or injury that needs prompt attention but is not an "
          "Emergency Medical Condition, such as a sprain, a minor cut or a high fever."),
    ("break", ""),

    ("major", "SECTION 3 - SCHEDULE OF BENEFITS"),
    ("minor", "3.1 Office Visits and Telehealth"),
    ("p", "Primary care visit to treat an injury or illness: In-Network $30 copay per visit, deductible does not "
          "apply. Out-of-Network: 50% coinsurance after deductible."),
    ("p", "Specialist visit: In-Network $60 copay per visit, deductible does not apply. Out-of-Network: 50% "
          "coinsurance after deductible. No referral is needed."),
    ("p", "Telehealth: visits through Evergreen Virtual Care cost $0. Telehealth visits with other Network "
          "Providers cost the same as an office visit with that provider."),
    ("minor", "3.2 Preventive Care"),
    ("p", "Preventive care, screenings and immunizations from Network Providers cost $0 and the deductible does "
          "not apply. This includes an annual physical exam, well-woman visits, well-child visits, recommended "
          "cancer screenings, FDA-approved contraception and vaccines recommended by the CDC. Out-of-Network "
          "preventive care: 50% coinsurance after deductible. If you receive diagnostic or treatment services "
          "during a preventive visit, you may owe cost-sharing for those services."),
    ("minor", "3.3 Urgent Care, Emergency Services and Ambulance"),
    ("p", "Urgent care center visit: $75 copay per visit, deductible does not apply, In-Network or "
          "Out-of-Network."),
    ("p", "Emergency room services: $400 copay per visit, deductible does not apply. The copay is waived if you "
          "are admitted to the hospital as an inpatient. Emergency room services from Out-of-Network providers "
          "are covered at the In-Network level. Prior Authorization is never required for emergency services."),
    ("p", "Ground ambulance: 30% coinsurance after deductible for medically necessary emergency transport, "
          "In-Network or Out-of-Network. Air ambulance: 30% coinsurance after deductible when ground transport "
          "would endanger your health."),
    ("break", ""),
    ("minor", "3.4 Diagnostic Tests and Imaging"),
    ("p", "Laboratory tests and X-rays: $0 at Evergreen preferred laboratories and imaging centers. At other "
          "Network Providers: 30% coinsurance after deductible. Out-of-Network: 50% coinsurance after deductible."),
    ("p", "Advanced imaging (MRI, CT, PET and nuclear medicine scans): In-Network 30% coinsurance after "
          "deductible. Out-of-Network 50% coinsurance after deductible. Prior Authorization is required for "
          "non-emergency advanced imaging (see Section 4)."),
    ("minor", "3.5 Hospital and Surgical Services"),
    ("p", "Inpatient hospital stay (facility and physician fees): In-Network 30% coinsurance after deductible. "
          "Out-of-Network 50% coinsurance after deductible. Prior Authorization is required for all "
          "non-emergency inpatient admissions."),
    ("p", "Outpatient surgery (facility and surgeon fees): In-Network 30% coinsurance after deductible. "
          "Out-of-Network 50% coinsurance after deductible."),
    ("minor", "3.6 Mental Health and Substance Use Disorder Services"),
    ("p", "Outpatient therapy and counseling visits: In-Network $30 copay per visit, deductible does not apply. "
          "There is no limit on the number of visits. Out-of-Network: 50% coinsurance after deductible."),
    ("p", "Inpatient and residential treatment: In-Network 30% coinsurance after deductible, with Prior "
          "Authorization for non-emergency admissions. Out-of-Network: 50% coinsurance after deductible."),
    ("minor", "3.7 Pregnancy, Maternity and Newborn Care"),
    ("p", "Prenatal care visits: $0 In-Network, deductible does not apply. Delivery and inpatient maternity "
          "services: In-Network 30% coinsurance after deductible. A newborn is covered from birth for 31 days; "
          "see Section 9 to keep the baby on the plan."),
    ("break", ""),
    ("minor", "3.8 Rehabilitation and Habilitation Services"),
    ("p", "Physical therapy, occupational therapy and speech therapy: In-Network $60 copay per visit, deductible "
          "does not apply. Limited to 30 visits per plan year for all three therapies combined. Out-of-Network: "
          "50% coinsurance after deductible, counted toward the same 30-visit limit."),
    ("p", "Chiropractic care: In-Network $40 copay per visit, limited to 12 visits per plan year. Not covered "
          "Out-of-Network."),
    ("minor", "3.9 Durable Medical Equipment"),
    ("p", "Durable medical equipment such as crutches, wheelchairs, CPAP machines and insulin pumps: 30% "
          "coinsurance after deductible. Prior Authorization is required for any single item costing more "
          "than $1,500."),
    ("minor", "3.10 Pediatric Dental and Vision Care"),
    ("p", "For members under age 19: one routine eye exam and one pair of eyeglasses or contact lenses per plan "
          "year at $0 In-Network. Pediatric dental check-ups and cleanings twice per plan year at $0; fillings and "
          "other basic dental services at 30% coinsurance after deductible."),
    ("minor", "3.11 Hearing Services"),
    ("p", "Hearing exams: In-Network $60 copay. Hearing aids for members under age 19: one hearing aid per ear "
          "every 36 months, 30% coinsurance after deductible. Hearing aids for adults are excluded (see 7.8)."),
    ("break", ""),

    ("major", "SECTION 4 - PRIOR AUTHORIZATION"),
    ("minor", "4.1 Services That Require Prior Authorization"),
    ("p", "You need Prior Authorization before receiving the following non-emergency services: inpatient hospital "
          "admissions; advanced imaging (MRI, CT, PET and nuclear medicine); outpatient surgeries performed in a "
          "hospital; bariatric surgery; durable medical equipment items costing more than $1,500; home health "
          "care; genetic testing; and specialty drugs (see Section 6)."),
    ("minor", "4.2 How to Get Prior Authorization"),
    ("p", "Network Providers request Prior Authorization for you. If you see an Out-of-Network provider, you or "
          "your provider must call 1-800-555-0142 before the service. Evergreen decides urgent requests within "
          "72 hours and standard requests within 7 calendar days, and will explain the reason for any denial."),
    ("minor", "4.3 What Happens If Prior Authorization Is Not Obtained"),
    ("p", "If a Network Provider fails to obtain a required Prior Authorization, the provider may not bill you "
          "for the service. If you use an Out-of-Network provider and Prior Authorization is not obtained, "
          "benefits for that service are reduced by 50%, up to a maximum reduction of $1,000 per service or "
          "admission. If Evergreen later determines the service was not Medically Necessary, it is not covered."),
    ("minor", "4.4 Emergencies"),
    ("p", "Prior Authorization is never required for emergency services. If you are admitted to a hospital after "
          "an emergency, you or the hospital should notify Evergreen within 48 hours, or as soon as reasonably "
          "possible."),
    ("break", ""),

    ("major", "SECTION 5 - CARE OUT OF NETWORK AND OUTSIDE THE UNITED STATES"),
    ("minor", "5.1 Out-of-Network Care"),
    ("p", "This PPO covers Out-of-Network care at the Out-of-Network benefit level shown in Section 3. "
          "Out-of-Network providers may bill you for charges above the Allowed Amount, except for emergency "
          "services, air ambulance services, and certain services at In-Network facilities that are protected "
          "by the federal No Surprises Act."),
    ("minor", "5.2 Care While Traveling in the United States"),
    ("p", "Urgent care and emergency services anywhere in the United States are covered as shown in Section 3.3. "
          "Routine care from providers outside the Evergreen Preferred Network is covered at the Out-of-Network "
          "level."),
    ("minor", "5.3 Care Outside the United States"),
    ("p", "Emergency services and urgent care received outside the United States are covered at the In-Network "
          "level of benefits. You may have to pay the provider yourself. To be reimbursed, submit an itemized "
          "bill, translated into English, with proof of payment within 12 months of the date of service."),
    ("p", "Non-emergency, routine or planned care received outside the United States is not covered. Medical "
          "evacuation and repatriation are not covered (see 7.10). Consider buying travel medical insurance "
          "before an international trip."),
    ("break", ""),

    ("major", "SECTION 6 - PRESCRIPTION DRUGS"),
    ("minor", "6.1 Drug Tiers and What You Pay"),
    ("p", "Costs below are for up to a 30-day supply at a network pharmacy. The deductible does not apply to "
          "Tier 1, Tier 2 or Tier 3 drugs."),
    ("p", "Tier 1 (generic drugs): $15 copay. Tier 2 (preferred brand drugs): $50 copay. Tier 3 (non-preferred "
          "brand drugs): $100 copay. Tier 4 (specialty drugs): 40% coinsurance after deductible, up to $500 per "
          "fill. Specialty drugs require Prior Authorization and must be filled at Evergreen Specialty Pharmacy."),
    ("minor", "6.2 Mail Order"),
    ("p", "You can get a 90-day supply of Tier 1, 2 and 3 maintenance drugs by mail for 2.5 times the 30-day "
          "copay."),
    ("minor", "6.3 Step Therapy and Exceptions"),
    ("p", "Some drugs require step therapy: you must try a lower-cost drug first. You or your doctor can ask for "
          "an exception. Evergreen decides exception requests within 72 hours, or within 24 hours if your health "
          "is at serious risk."),
    ("minor", "6.4 Insulin and Diabetes Drugs"),
    ("p", "Insulin costs $35 per 30-day supply, deductible does not apply. GLP-1 drugs such as semaglutide are "
          "covered as Tier 3 drugs with Prior Authorization when prescribed to treat type 2 diabetes. Drugs "
          "prescribed primarily for weight loss are excluded (see 7.5)."),
    ("break", ""),

    ("major", "SECTION 7 - EXCLUSIONS AND LIMITATIONS"),
    ("p", "This plan does not cover the services listed in this section, even if a provider recommends them, "
          "unless this section says otherwise."),
    ("minor", "7.1 General Exclusions"),
    ("p", "Services that are not Medically Necessary; experimental or investigational treatments; services "
          "provided by a member of your immediate family; services covered by workers' compensation; and "
          "charges for missed appointments or for completing forms."),
    ("minor", "7.2 Cosmetic Services"),
    ("p", "Cosmetic surgery and procedures whose main purpose is to improve appearance are not covered. "
          "Reconstructive surgery is covered when it repairs damage from an accident, injury or illness, follows "
          "a mastectomy, or corrects a congenital defect in a child."),
    ("minor", "7.3 Dental and Vision Services"),
    ("p", "(a) Pediatric dental and vision services are covered as described in Section 3.10."),
    ("p", "(b) Routine dental care for members age 19 and older is not covered. This includes cleanings, "
          "X-rays, fillings, crowns, root canals, extractions, orthodontics, implants and dentures."),
    ("p", "(c) Treatment of an accidental injury to sound natural teeth is covered for members of any age if "
          "treatment begins within 60 days of the injury."),
    ("p", "(d) Routine eye exams, eyeglasses and contact lenses for members age 19 and older are not covered."),
    ("p", "(e) LASIK and other refractive eye surgery are not covered."),
    ("minor", "7.4 Infertility Services"),
    ("p", "Services to diagnose infertility are covered. In vitro fertilization (IVF), artificial insemination, "
          "egg or embryo freezing, and fertility drugs are not covered."),
    ("break", ""),
    ("minor", "7.5 Weight Management"),
    ("p", "(a) Bariatric surgery is covered with Prior Authorization for members with a body mass index (BMI) of "
          "40 or more, or 35 or more with a serious weight-related condition such as type 2 diabetes, after "
          "completing a six-month physician-supervised weight management program."),
    ("p", "(b) Drugs prescribed primarily for weight loss are not covered, including GLP-1 drugs used for "
          "weight loss rather than diabetes treatment."),
    ("p", "(c) Commercial weight loss programs, gym or fitness memberships and diet foods are not covered."),
    ("minor", "7.6 Alternative Medicine"),
    ("p", "Acupuncture is covered only for chronic low back pain, up to 12 visits per plan year at the Specialist "
          "copay. Massage therapy, naturopathy, homeopathy and hypnotherapy are not covered."),
    ("minor", "7.7 Custodial and Long-Term Care"),
    ("p", "Custodial care, meaning help with daily activities such as bathing, dressing and eating that does not "
          "require skilled medical staff, is not covered, including in a nursing home or at home. Long-term care "
          "is not covered."),
    ("minor", "7.8 Hearing Aids for Adults"),
    ("p", "Hearing aids for members age 19 and older are not covered. Hearing exams are covered as described in "
          "Section 3.11."),
    ("minor", "7.9 Travel-Related Services"),
    ("p", "Physical exams, certificates or paperwork required only for travel, employment or insurance are not "
          "covered."),
    ("minor", "7.10 Medical Evacuation and Repatriation"),
    ("p", "Transportation back to the United States for medical care (medical evacuation) and the return of "
          "remains (repatriation) are not covered."),
    ("break", ""),

    ("major", "SECTION 8 - CLAIMS AND APPEALS"),
    ("minor", "8.1 Filing a Claim"),
    ("p", "Network Providers file claims for you. For Out-of-Network or foreign care, send an itemized bill and "
          "proof of payment to Evergreen Claims within 12 months of the date of service. Claims submitted later "
          "are not paid unless you could not reasonably file on time."),
    ("minor", "8.2 If Your Claim Is Denied"),
    ("p", "If Evergreen denies a claim or a Prior Authorization request, you will receive a written notice that "
          "explains the reason, the plan provision used, and how to appeal."),
    ("minor", "8.3 Internal Appeals"),
    ("p", "You may file an internal appeal within 180 days of receiving a denial notice, by phone, mail or the "
          "member website. Evergreen decides appeals within 30 days for services not yet received, 60 days for "
          "services already received, and 72 hours for urgent care. You may submit letters from your doctor and "
          "other information, and you may ask for a free copy of your claim file."),
    ("minor", "8.4 External Review"),
    ("p", "If your internal appeal is denied, you may ask for an external review by an Independent Review "
          "Organization within 4 months of the final denial notice. The external reviewer's decision is binding "
          "on Evergreen. Expedited external review is available for urgent situations."),
    ("minor", "8.5 Getting Help"),
    ("p", "Call Evergreen Member Services at 1-800-555-0142. You can also contact your state department of "
          "insurance for help with a complaint or appeal."),
    ("break", ""),

    ("major", "SECTION 9 - ELIGIBILITY AND ENROLLMENT"),
    ("minor", "9.1 Who Can Be Covered"),
    ("p", "The subscriber, the subscriber's spouse or domestic partner, and children under age 26, whether or "
          "not they are married, live with you or are financially dependent on you."),
    ("minor", "9.2 Adding a Newborn or Adopted Child"),
    ("p", "A newborn is covered automatically for the first 31 days after birth. To keep the child covered, "
          "enroll the child within 60 days of birth. Adopted children are covered from the date of placement if "
          "enrolled within 60 days."),
    ("minor", "9.3 Special Enrollment Periods"),
    ("p", "You can enroll or change plans outside open enrollment within 60 days of a qualifying life event, such "
          "as losing other coverage, getting married, having a baby or moving to a new area."),
    ("minor", "9.4 When Coverage Ends"),
    ("p", "Coverage ends if premiums are not paid by the end of a 31-day grace period, if you are no longer "
          "eligible, or if you commit fraud. Evergreen will not cancel coverage retroactively except for fraud or "
          "non-payment of premiums, and will give 30 days' notice."),
    ("break", ""),

    ("major", "SECTION 10 - COVERAGE EXAMPLES"),
    ("p", "These examples show how this plan might cover care. Actual costs depend on the care you receive and "
          "the Allowed Amounts. All examples assume In-Network care and that the member has not met any of the "
          "deductible yet."),
    ("minor", "10.1 Having a Baby"),
    ("p", "Peg has a normal delivery at a network hospital. Total Allowed Amount: $12,700. Peg pays the $3,000 "
          "deductible, then 30% coinsurance on the remaining $9,700 ($2,910). Prenatal visits cost $0. Total Peg "
          "pays: $5,910. The plan pays $6,790."),
    ("minor", "10.2 A Simple Fracture"),
    ("p", "Mia breaks her arm. She visits a network emergency room ($400 copay), gets X-rays at an Evergreen "
          "preferred imaging center ($0), sees an orthopedic Specialist twice ($60 copay each) and has 4 physical "
          "therapy visits ($60 copay each). Total Mia pays: $760, none of it subject to the deductible."),
    ("minor", "10.3 An MRI for Knee Pain"),
    ("p", "Sam's doctor orders a knee MRI at a network imaging center with Prior Authorization. Allowed Amount: "
          "$1,800. Sam has not met the deductible, so Sam pays the full $1,800, which counts toward the $3,000 "
          "deductible."),
]


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6)
    major = ParagraphStyle("major", parent=styles["Heading1"], fontSize=15, spaceBefore=4, spaceAfter=10)
    minor = ParagraphStyle("minor", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4)
    title = ParagraphStyle("title", parent=styles["Title"], fontSize=24, spaceAfter=6)
    title2 = ParagraphStyle("title2", parent=styles["Heading2"], alignment=1, spaceAfter=24)
    style_for = {"p": body, "major": major, "minor": minor, "title": title, "title2": title2}

    story = []
    for kind, text in CONTENT:
        if kind == "break":
            story.append(PageBreak())
        else:
            story.append(Paragraph(text, style_for[kind]))
            if kind == "title2":
                story.append(Spacer(1, 0.2 * inch))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(LETTER[0] / 2, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(PDF_PATH), pagesize=LETTER, title="Evergreen Silver 3000 PPO - Evidence of Coverage (sample)",
        author="Am I Covered? demo", leftMargin=0.9 * inch, rightMargin=0.9 * inch,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    FACTS_PATH.write_text(json.dumps(PLAN_FACTS, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {PDF_PATH} and {FACTS_PATH}")


if __name__ == "__main__":
    build()
