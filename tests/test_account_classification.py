import unittest

from services.account_classification import (
    classify_email,
    is_student_domain_email,
    is_valid_student_email,
    resolve_signup_role_name,
)


class StudentEmailClassificationTests(unittest.TestCase):
    def test_valid_student_email_is_student(self):
        self.assertTrue(is_valid_student_email("john222-35-456@diu.edu.bd"))
        self.assertEqual(classify_email("john222-35-456@diu.edu.bd"), "student")

    def test_missing_name_prefix_rejected(self):
        # The ID block alone, with no name in front, no longer qualifies.
        self.assertFalse(is_valid_student_email("222-35-456@diu.edu.bd"))

    def test_name_must_come_before_id_not_after(self):
        self.assertFalse(is_valid_student_email("222-35-456john@diu.edu.bd"))

    def test_gmail_lookalike_id_is_not_student(self):
        self.assertFalse(is_valid_student_email("john222-35-456@gmail.com"))
        self.assertEqual(classify_email("john222-35-456@gmail.com"), "external")

    def test_missing_dashes_rejected(self):
        self.assertFalse(is_valid_student_email("john22235456@diu.edu.bd"))

    def test_short_final_group_rejected(self):
        self.assertFalse(is_valid_student_email("john222-35-45@diu.edu.bd"))

    def test_four_digit_final_group_accepted(self):
        # Departments with enrollment over 999 roll the ID over to 4
        # digits, e.g. john242-15-7318@diu.edu.bd.
        self.assertTrue(is_valid_student_email("john242-15-7318@diu.edu.bd"))
        self.assertEqual(classify_email("john242-15-7318@diu.edu.bd"), "student")

    def test_five_digit_final_group_rejected(self):
        self.assertFalse(is_valid_student_email("john242-15-73185@diu.edu.bd"))

    def test_domain_suffix_spoof_rejected(self):
        self.assertFalse(
            is_valid_student_email("john222-35-456@diu.edu.bd.attacker.com")
        )

    def test_non_id_localpart_on_diu_domain_rejected(self):
        self.assertFalse(is_valid_student_email("student@diu.edu.bd"))

    def test_plain_gmail_is_external(self):
        self.assertEqual(classify_email("sourav@gmail.com"), "external")
        self.assertEqual(classify_email("vendor@gmail.com"), "external")

    def test_official_diu_domain_exact_match(self):
        self.assertEqual(
            classify_email("registrar@daffodilvariversity.edu.bd"), "official_diu"
        )

    def test_official_diu_domain_prefix_spoof_rejected(self):
        # "fake-daffodilvariversity.edu.bd" must NOT match via substring.
        self.assertEqual(
            classify_email("someone@fake-daffodilvariversity.edu.bd"), "external"
        )

    def test_official_diu_domain_suffix_spoof_rejected(self):
        self.assertEqual(
            classify_email("someone@daffodilvariversity.edu.bd.attacker.com"),
            "external",
        )

    def test_is_student_domain_email_flags_malformed_diu_address(self):
        # Domain matches diu.edu.bd but the ID pattern doesn't -- this
        # must be caught and rejected outright, not silently downgraded
        # to a plain external/student account.
        self.assertTrue(is_student_domain_email("student@diu.edu.bd"))
        self.assertFalse(is_valid_student_email("student@diu.edu.bd"))

    def test_case_insensitivity(self):
        self.assertEqual(classify_email("john222-35-456@DIU.EDU.BD"), "student")

    def test_resolve_signup_role_name_never_returns_admin_or_vendor(self):
        for email in (
            "john222-35-456@diu.edu.bd",
            "vendor@gmail.com",
            "registrar@daffodilvariversity.edu.bd",
        ):
            role_name, _classification = resolve_signup_role_name(email)
            self.assertEqual(role_name, "student")

    def test_resolve_signup_role_name_student_email_gets_student_role(self):
        role_name, classification = resolve_signup_role_name(
            "john222-35-456@diu.edu.bd"
        )
        self.assertEqual(role_name, "student")
        self.assertEqual(classification, "student")

    def test_resolve_signup_role_name_external_also_resolves_to_student(self):
        # "student" is the only role self-service signup can ever
        # produce -- is_allowed_signup_email is what actually blocks a
        # non-DIU email from reaching account creation at all; this
        # function no longer has a separate "customer" role to fall
        # back to.
        role_name, classification = resolve_signup_role_name("vendor@gmail.com")
        self.assertEqual(role_name, "student")
        self.assertEqual(classification, "external")


if __name__ == "__main__":
    unittest.main()
