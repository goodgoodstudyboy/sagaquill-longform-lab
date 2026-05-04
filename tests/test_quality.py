from __future__ import annotations

import unittest

from sagaquill.models import CharacterVoiceCard, ProgressionLedgerItem
from sagaquill.quality import analyze_chapter, analyze_novel, dedupe_repeated_paragraphs


class QualityTests(unittest.TestCase):
    def test_quality_passes_for_reasonable_text(self) -> None:
        text = (
            "沈雾把湿透的雨衣挂在门后，招领室里全是旧木头发潮的味道。\n\n"
            "她刚把那只旧怀表摆正，指针就像被谁轻轻拨了一下，往回倒退了一秒。\n\n"
            "门口站着一个男孩，鞋边沾着海泥，却死死盯着玻璃柜里的表，像盯着一口井。\n\n"
            "沈雾没有立刻开口，只把登记簿推过去。男孩抬头时，她在他眼里看见了熟悉的惊慌。"
        )
        report = analyze_chapter(text, 120, ["沈雾"])
        self.assertTrue(report.passed)
        self.assertGreaterEqual(report.score, 70)

    def test_quality_fails_for_placeholders(self) -> None:
        text = "TODO 这里略去关键剧情。"
        report = analyze_chapter(text, 200, ["沈雾"])
        self.assertFalse(report.passed)
        self.assertTrue(any("占位词" in issue for issue in report.issues))

    def test_quality_does_not_flag_in_world_waiting_term_as_placeholder(self) -> None:
        text = (
            "林渊伏低身形，听见坡后的灰影沿裂波逼近。\n\n"
            "为首那人压着嗓子喝了一句：“沿裂波！活口在前，主证不散，落标待补收！”\n\n"
            "韩北斗没回头，只把刀背往下压，示意苏晚照继续看碑。"
        )
        report = analyze_chapter(text, 60, ["林渊"])
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["placeholder_hits"], [])

    def test_novel_quality_flags_standalone_teaser_ending(self) -> None:
        chapters = [
            "沈雾追到了旧影院门口，决定继续查下去。",
            "门外站着个送件员，怀里抱着一只包得严严实实的旧物，标签上写着：长期无人认领。"
        ]
        report = analyze_novel(chapters, 40, ending_mode="standalone")
        self.assertFalse(report.passed)
        self.assertTrue(any("收束感不足" in issue for issue in report.issues))

    def test_novel_quality_allows_tiny_duplicate_noise_in_very_long_book(self) -> None:
        duplicate_paragraph = "沈雾把湿透的卷页摊在灯下，先压平边角，再去认那一行几乎被水泡开的旧字。"
        chapters: list[str] = []
        for index in range(220):
            opening = "风从旧城墙缺口灌进来。" if index in (0, 1) else f"第{index}夜的潮气还没散。"
            body = duplicate_paragraph if index in (10, 120) else f"沈雾第{index}次翻开旧卷宗，看见编号{index}旁边多了一道新划痕。"
            closing = f"她把第{index}份记录重新归档，决定继续往下查。"
            chapters.append(f"{opening}\n\n{body}\n\n{closing}")

        report = analyze_novel(chapters, 80, ending_mode="standalone")

        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["duplicate_paragraphs"], 1)
        self.assertEqual(report.metrics["duplicate_openings"], 1)

    def test_tomato_novel_quality_softens_mild_total_length_overflow(self) -> None:
        chapters = [
            "\n\n".join([f"第{index}章第一段" + ("甲" * 520), f"第{index}章第二段" + ("乙" * 520)])
            for index in range(1, 4)
        ]
        report = analyze_novel(
            chapters,
            2000,
            ending_mode="series",
            market_profile="tomato_mass",
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["novel_length_signal_level"], "warning")
        self.assertTrue(report.metrics["novel_length_warning"])

    def test_tomato_novel_quality_hard_fails_for_severe_total_length_overflow(self) -> None:
        chapters = [
            "\n\n".join([f"第{index}章第一段" + ("甲" * 780), f"第{index}章第二段" + ("乙" * 780)])
            for index in range(1, 4)
        ]
        report = analyze_novel(
            chapters,
            2000,
            ending_mode="series",
            market_profile="tomato_mass",
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["novel_length_signal_level"], "hard_fail")
        self.assertTrue(report.metrics["novel_length_hard_fail"])

    def test_hard_progression_chapter_warns_without_step_type_but_does_not_fail(self) -> None:
        text = (
            "韩立把药炉余温压住，先看洞府阵纹，再看案上的残页。\n\n"
            "他没有立刻动手突破，只先把两份辅药和那枚借来的内丹摆开，重新算了一遍今夜的风险。\n\n"
            "洞府外的风压着松针往石阶下滚，他顺手把护脉符挪近火口，免得灵气一散就白熬一夜。\n\n"
            "直到天将亮，他才把药性、灵力和自身暗伤一项项记清，准备下一次真正冲关。"
        )
        report = analyze_chapter(
            text,
            260,
            progression_mode="hard_realm_progression",
            progression_flavor="xianxia_steady",
            current_tier="练气九层",
            target_tier="筑基",
        )
        self.assertTrue(report.passed)
        self.assertTrue(any("progression_step_type" in issue for issue in report.issues))
        self.assertEqual(report.metrics["progression_signal_level"], "warning")

    def test_hard_progression_chapter_marks_fake_breakthrough_as_debt(self) -> None:
        text = (
            "林动盘膝坐下，四周元力被他强行拖进体内。\n\n"
            "他心神一动，便说自己已经跨过了最难的一步。"
        )
        report = analyze_chapter(
            text,
            120,
            progression_mode="hard_realm_progression",
            progression_flavor="xuanhuan_fast",
            progression_step_type="breakthrough",
            current_tier="地元境",
            target_tier="地元境",
        )
        self.assertTrue(any("突破章" in issue for issue in report.issues))
        self.assertTrue(report.metrics["progression_debt"])

    def test_hard_progression_novel_fails_when_ledger_never_advances(self) -> None:
        chapters = [f"第{i}章里主角一直在赶路和盘算。" for i in range(1, 45)]
        ledger = [
            ProgressionLedgerItem(
                milestone_label="筑基",
                current_tier="练气",
                target_tier="筑基",
                status="pending",
                objective="拿到筑基丹",
            )
        ]
        report = analyze_novel(
            chapters,
            10000,
            ending_mode="series",
            progression_mode="hard_realm_progression",
            progression_flavor="xianxia_steady",
            progression_ledger=ledger,
        )
        self.assertFalse(report.passed)
        self.assertTrue(report.metrics["progression_hard_fail"])

    def test_hard_progression_novel_accepts_meaningful_ledger_progress(self) -> None:
        chapters = [f"第{i}章里主角在试炼、拿资源和突破之间稳步推进。" for i in range(1, 45)]
        ledger = [
            ProgressionLedgerItem(
                milestone_label="筑基",
                current_tier="筑基",
                target_tier="筑基",
                status="advanced",
                objective="完成第一次大境界突破",
                unlocked_rewards=["寿元增长"],
            ),
            ProgressionLedgerItem(
                milestone_label="结丹",
                current_tier="筑基后期",
                target_tier="结丹",
                status="pending",
                objective="准备下一阶段试炼",
            ),
        ]
        report = analyze_novel(
            chapters,
            10000,
            ending_mode="series",
            progression_mode="hard_realm_progression",
            progression_flavor="xianxia_steady",
            progression_ledger=ledger,
        )
        self.assertTrue(report.passed)
        self.assertFalse(report.metrics["progression_hard_fail"])
        self.assertFalse(any("progression_step_type" in issue for issue in report.issues))

    def test_quality_does_not_hard_fail_for_short_dialogue_repetition(self) -> None:
        text = (
            "沈雾把登记簿压住，先看门口，再看那块旧表。\n\n"
            "“知道了。”\n\n"
            "她把旧表翻过来，确认背壳划痕和旧案记录一致。\n\n"
            "“知道了。”\n\n"
            "门外的潮声把窗纸吹得发响，她还是没有后退。\n\n"
            "“知道了。”\n\n"
            "她把钥匙揣进口袋，决定今晚就去旧影院。"
        )
        report = analyze_chapter(text, 120, ["沈雾"])
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["duplicate_paragraphs"], 0)
        self.assertGreaterEqual(report.metrics["duplicate_short_paragraphs"], 2)

    def test_quality_accepts_chapter_length_within_tolerance_band(self) -> None:
        paragraphs = [
            f"沈雾沿着第{index}段堤岸慢慢往前走，潮气一层层压低视线，她一边记下岸边铁桩的编号，一边分辨风里混着的机油味和海腥味，直到远处最后一盏灯也被水雾磨成钝钝的一小团。她顺手把怀里的旧账页翻到下一面，又在页边补了一笔关于潮位、风向和巡堤脚步的注记，免得回去后把今晚这段异样的安静记错。"
            for index in range(1, 13)
        ]
        text = "\n\n".join(paragraphs)
        report = analyze_chapter(text, 2000, ["沈雾"], length_tolerance=0.25)
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["target_chars_min"], 1500)
        self.assertEqual(report.metrics["target_chars_max"], 2500)

    def test_quality_flags_chapter_length_outside_tolerance_band(self) -> None:
        paragraphs = [
            f"沈雾只来得及把第{index}张欠条塞进口袋，就听见门外有人拍了三下木门。她没有立刻应声，而是先把桌上的潮痕擦净，再把门闩抬起半寸，借着缝隙去看对方靴边沾着的煤灰和雨泥，想判断来人究竟是催债的、送信的，还是旧案里那批一直不肯露面的跟踪者。她顺手把桌上的账页按编号重新排了一遍，又记下雨声里夹着的车轮动静和门外呼吸停顿的次数，越看越觉得这次上门的人不像普通催收，而像冲着旧库房留下的那笔折账记录来的。"
            for index in range(1, 19)
        ]
        text = "\n\n".join(paragraphs)
        report = analyze_chapter(text, 2000, ["沈雾"], length_tolerance=0.25)
        self.assertFalse(report.passed)
        self.assertTrue(any("高于目标区间上限" in issue for issue in report.issues))

    def test_quality_allows_small_overflow_with_editorial_grace(self) -> None:
        text = "\n\n".join(["甲" * 450, "乙" * 450, "丙" * 450, "丁" * 429])
        report = analyze_chapter(text, 1400, length_tolerance=0.25)
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["char_count"], 1779)
        self.assertEqual(report.metrics["target_chars_max"], 1750)
        self.assertEqual(report.metrics["target_chars_hard_max"], 1780)
        self.assertTrue(any("发行前建议再压字" in issue for issue in report.issues))

    def test_quality_prefers_explicit_plan_bounds_over_derived_tolerance(self) -> None:
        paragraphs = [
            part
            for index in range(1, 3)
            for part in (
                (
                    f"顾长生把第{index}页旧案卷摊开在桌上，先核借命类型，再核抵押物，又把酉时三刻和回棚屋的脚程在心里过了一遍。"
                    f"第{index}次翻到展期记录时，他都要顺手摸一摸袖中的碎钱，确认自己还能不能替沈蘅凑出今晚那半副吊命药。"
                    f"这一页边角磨得最厉害，顾长生便把它单独压平，再记下第{index}条异常链路，生怕漏掉哪个能让人活下去的细节。"
                ),
                (
                    f"胡执事把第{index}份退回卷宗往他面前一推时，连语气都像在说这只是给见习催命吏准备的废纸。"
                    f"顾长生没有立刻接话，而是先把第{index}笔抽成和脚程写在掌心，算清自己若今日不出门，夜里会在哪一步先断气。"
                    f"他听着门外催差敲过第{index}声竹牌，反而把呼吸压得更平，只想把这烂账里真正要命的地方先找出来。"
                ),
                (
                    f"药铺掌柜提起第{index}种最便宜的吊命药时，顾长生先看药渣颜色，再看火候，最后才问价。"
                    f"他知道自己买不起整副药，所以把第{index}次问价的羞耻一起吞下，只在心里把收账回来的抽成拆成米、灯油和止血散。"
                    f"回院子的路不算长，可他每走到第{index}块裂砖旁，都会想起沈蘅夜里那阵压不住的咳声。"
                ),
                (
                    f"催命印在第{index}次触到卷宗时发烫得更狠，像有人把一根细针从骨缝里慢慢推出来。"
                    f"顾长生盯着浮出的借命字段看了第{index}眼，终于确认这不是普通拖账，而是一条被人临时遮掩过的脏链。"
                    f"他把抵押物、展期次数和异常残痕逐一记在纸边，宁肯慢一点，也不肯把周顺这条线看成寻常坊市赖账。"
                ),
                (
                    f"回到破院时，灯芯已经短到只剩第{index}截，昏黄火苗把土墙上的裂缝照得像旧伤。"
                    f"顾长生先把水碗递到沈蘅唇边，又把第{index}次问来的药价在心里默念一遍，免得自己被那点绝望压得乱了章法。"
                    f"等催命印在母亲头顶晃出模糊旧债影子时，他反倒彻底定下心来，知道今夜这单账非去不可。"
                ),
                (
                    f"他重新束好袖口时，顺手把第{index}张散开的旧纸塞回案卷里，像把自己最后一点犹豫一并压住。"
                    f"顾长生很清楚，见习差役没有资格挑活，所以他只能把第{index}层风险拆开来看，先找能动手的命门，再想后退的路。"
                    f"院门外的风越刮越冷，他却在这种发紧的安静里把今晚的路线一点点算明白。"
                ),
                (
                    f"坊市里传过来的脚步声一阵紧一阵松，顾长生听到第{index}拨夜巡换岗时，已经把周顺那边可能出现的反扑想了七八种。"
                    f"他不信天命司会把真正干净的账扔给自己，于是又对着第{index}条批注看了半晌，只想弄清前手到底在怕什么。"
                    f"纸上的空白越多，他心里那点活命的贪念反而越硬，因为只有这种脏账里才可能藏着翻身的余地。"
                ),
                (
                    f"沈蘅昏睡时手指还扣着旧褥角，顾长生替她掖被时，忽然发现第{index}道旧线似乎一直绕在她身上。"
                    f"他没有立刻去碰那团模糊影子，只把药炉余温、床边空碗和柜里剩下的碎钱一起记清，像在替自己立一份不能回头的账。"
                    f"若今晚再空手回来，第{index}样能保命的东西都会先一步耗尽，这个念头像钉子一样把他钉在门口。"
                ),
                (
                    f"顾长生把收账要用的物件排成一列时，连第{index}根针、第{index}道符灰和第{index}截旧绳都重新看过。"
                    f"他知道自己不是去逞强，而是去和一个快到酉时的死账抢半口活气，所以每一步都先按穷人的算法去算。"
                    f"等他把案卷重新揣进怀里，整个人已经像绷紧的弓弦，只剩最后一下出门的力。"
                ),
            )
        ]
        text = "\n\n".join(paragraphs)
        report = analyze_chapter(
            text,
            2320,
            ["顾长生", "沈蘅"],
            length_tolerance=0.25,
            target_chars_min=1898,
            target_chars_max=3164,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["target_chars_min"], 1898)
        self.assertEqual(report.metrics["target_chars_max"], 3164)

    def test_quality_relaxes_length_gate_for_mid_long_form_until_extreme_overflow(self) -> None:
        text = "\n\n".join(
            [
                f"第{index}段" + ("甲" * 430)
                for index in range(1, 7)
            ]
        )
        report = analyze_chapter(
            text,
            2000,
            strict_length_gate=False,
            target_chars_min=1500,
            target_chars_max=2500,
        )
        self.assertTrue(report.passed)
        self.assertFalse(report.metrics["strict_length_gate"])
        self.assertGreater(report.metrics["char_count"], report.metrics["target_chars_hard_max"])
        self.assertLessEqual(report.metrics["char_count"], report.metrics["target_chars_extreme_max"])

    def test_quality_still_fails_for_extreme_mid_long_form_overflow(self) -> None:
        text = "\n\n".join(
            [
                f"第{index}段" + ("甲" * 430)
                for index in range(1, 19)
            ]
        )
        report = analyze_chapter(
            text,
            2000,
            strict_length_gate=False,
            target_chars_min=1500,
            target_chars_max=2500,
        )
        self.assertFalse(report.passed)
        self.assertGreater(report.metrics["char_count"], report.metrics["target_chars_extreme_max"])

    def test_tomato_profile_softens_length_gate_for_mild_long_form_overflow(self) -> None:
        text = "\n\n".join(
            [
                f"第{index}段" + ("甲" * 430)
                for index in range(1, 7)
            ]
        )
        report = analyze_chapter(
            text,
            2000,
            market_profile="tomato_mass",
            strict_length_gate=False,
            target_chars_min=1500,
            target_chars_max=2500,
        )
        self.assertTrue(report.passed)
        self.assertFalse(report.metrics["strict_length_gate"])
        self.assertIn(report.metrics["length_signal_level"], {"ok", "warning"})
        self.assertLessEqual(report.metrics["target_chars_extreme_max"], 6000)

    def test_tomato_profile_only_hard_fails_for_severe_long_form_overflow(self) -> None:
        text = "\n\n".join(
            [
                f"第{index}段" + ("甲" * 430)
                for index in range(1, 15)
            ]
        )
        report = analyze_chapter(
            text,
            2000,
            market_profile="tomato_mass",
            strict_length_gate=False,
            target_chars_min=1500,
            target_chars_max=2500,
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["length_signal_level"], "hard_fail")

    def test_tomato_profile_softens_mild_underlength(self) -> None:
        text = "\n\n".join(
            [
                "甲" * 460,
                "乙" * 460,
                "丙" * 460,
                "丁" * 460,
            ]
        )
        report = analyze_chapter(
            text,
            2400,
            market_profile="tomato_mass",
            strict_length_gate=False,
            target_chars_min=1900,
            target_chars_max=3100,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["length_signal_level"], "warning")
        self.assertTrue(report.metrics["length_warning"])

    def test_tomato_profile_hard_fails_only_for_severe_underlength(self) -> None:
        text = "\n\n".join(
            [
                "甲" * 160,
                "乙" * 160,
                "丙" * 160,
                "丁" * 160,
            ]
        )
        report = analyze_chapter(
            text,
            2400,
            market_profile="tomato_mass",
            strict_length_gate=False,
            target_chars_min=1900,
            target_chars_max=3100,
        )
        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["length_signal_level"], "hard_fail")
        self.assertTrue(report.metrics["length_hard_fail"])

    def test_dedupe_repeated_paragraphs_removes_long_duplicate_blocks(self) -> None:
        text = (
            "沈雾看见旧表先是一愣，接着把掌心慢慢压在冰凉的柜台边沿，确认自己没有认错那道划痕。\n\n"
            "她没有立刻去碰，只把登记簿翻到空白页，盯着那串编号像盯着半年前没写完的一句话。\n\n"
            "沈雾看见旧表先是一愣，接着把掌心慢慢压在冰凉的柜台边沿，确认自己没有认错那道划痕。\n\n"
            "她最后还是把表拿起来，决定去旧影院把这条线追到底。"
        )
        cleaned, removed = dedupe_repeated_paragraphs(text)
        self.assertEqual(removed, 1)
        self.assertEqual(cleaned.count("沈雾看见旧表先是一愣"), 1)

    def test_quality_flags_dense_procedural_language_when_term_budget_is_low(self) -> None:
        text = (
            "顾平生把总赔单、回补单、对单表和核算口径逐条摊开，先对编号，再对字段，再让账房把留档凭证和报备票据一并抄到台账旁边。\n\n"
            "他没有抬头，只让燕无咎照着流程把赔付名单、停单说明、递送链回执和旧口供一起压在清单下，再逐条核验口径、索引、凭证和条款有没有互相打架。\n\n"
            "门外的人声越挤越近，他还是按着表格把字段、编号、账页、票据和口供一项项圈出来，逼着众人先认流程，再认责任。 "
        )
        report = analyze_chapter(
            text,
            360,
            ["顾平生", "燕无咎"],
            term_budget="low",
        )
        self.assertTrue(any("术语和流程信息偏密" in issue for issue in report.issues))

    def test_quality_flags_repeated_propulsion_engine(self) -> None:
        text = (
            "顾平生接过新送来的账页，先对编号，再拆口供，最后顺着票据把新的缺口指给众人看。\n\n"
            "他没有解释太多，只继续拿证、并证、再抬一级，让屋里的人全都跟着那张账页转。\n\n"
            "燕无咎把门口的人压住，不让任何人先散。\n\n"
            "顾平生最后只把那一页按在桌角，说明天还要照同一路数再往上抬。"
        )
        report = analyze_chapter(
            text,
            120,
            ["顾平生"],
            current_propulsion="证据推进",
            recent_propulsion_history=["证据推进", "证据推进", "程序拆解"],
            chapter_role="investigation",
            scene_types=["public_pressure", "evidence_push"],
            variation_goal="公开施压，再抬一级",
            recent_stagnation_history=[
                {
                    "primary_propulsion": "程序拆解",
                    "chapter_role": "investigation",
                    "variation_goal": "拆口径",
                    "scene_types": ["process_check"],
                },
                {
                    "primary_propulsion": "证据推进",
                    "chapter_role": "investigation",
                    "variation_goal": "公开施压，再抬一级",
                    "scene_types": ["public_pressure", "evidence_push"],
                },
                {
                    "primary_propulsion": "证据推进",
                    "chapter_role": "investigation",
                    "variation_goal": "公开施压，再抬一级",
                    "scene_types": ["public_pressure", "evidence_push"],
                },
            ],
        )
        self.assertTrue(report.passed)
        self.assertTrue(report.metrics["stagnation_warning"])
        self.assertTrue(any("空转" in issue for issue in report.issues))

    def test_quality_escalates_for_severe_propulsion_repetition(self) -> None:
        text = (
            "顾平生把第三份口供摊平，继续按上一轮的方式并证、找缺口、抬层级。\n\n"
            "他连换气都没有，还是靠新证据把众人再往更深一层的节点里推。\n\n"
            "燕无咎在旁边只负责把围过来的人顶住，不让他们打断这套老路数。\n\n"
            "到章末时，局面仍然只是同一种公开施压再抬一级，没有换出新的后果。"
        )
        report = analyze_chapter(
            text,
            120,
            ["顾平生"],
            current_propulsion="证据推进",
            recent_propulsion_history=["证据推进"] * 9 + ["关系推进"],
            chapter_role="investigation",
            scene_types=["public_pressure", "evidence_push"],
            variation_goal="公开施压，再抬一级",
            recent_stagnation_history=[
                {
                    "primary_propulsion": "关系推进",
                    "chapter_role": "relationship",
                    "variation_goal": "试探",
                    "scene_types": ["private_talk"],
                }
            ]
            + [
                {
                    "primary_propulsion": "证据推进",
                    "chapter_role": "investigation",
                    "variation_goal": "公开施压，再抬一级",
                    "scene_types": ["public_pressure", "evidence_push"],
                }
                for _ in range(9)
            ],
        )
        self.assertTrue(report.passed)
        self.assertTrue(report.metrics["stagnation_escalation"])
        self.assertFalse(report.metrics["propulsion_hard_fail"])

    def test_quality_allows_same_family_when_function_changes(self) -> None:
        text = (
            "顾平生仍沿着旧账追查，但这一次没有再公开施压，只是在后院把伤药递给燕无咎，"
            "逼他先把代价说清，再决定明天要不要把账页送上去。\n\n"
            "燕无咎没有再争，只说先把命保住。\n\n"
            "顾平生这次也没把话题抬回众人面前，而是先确认谁来承担后手。\n\n"
            "两人没有再抬同一个口径，而是把是否继续推进，变成了一次明确的关系决断。"
        )
        report = analyze_chapter(
            text,
            120,
            ["顾平生", "燕无咎"],
            current_propulsion="证据推进",
            recent_propulsion_history=["证据推进", "证据推进", "证据推进"],
            chapter_role="afterglow",
            scene_types=["relationship_shift", "cost_payment"],
            variation_goal="先处理代价，再决定要不要继续追",
            recent_stagnation_history=[
                {
                    "primary_propulsion": "证据推进",
                    "chapter_role": "investigation",
                    "variation_goal": "公开施压，再抬一级",
                    "scene_types": ["public_pressure", "evidence_push"],
                }
                for _ in range(3)
            ],
        )
        self.assertTrue(report.passed)
        self.assertFalse(report.metrics["stagnation_warning"])
        self.assertFalse(report.metrics["stagnation_debt"])
        self.assertFalse(report.metrics["stagnation_escalation"])

    def test_quality_flags_ending_voice_convergence(self) -> None:
        text = (
            "顾平生看着门外的雨，说自己会继续往前查。\n\n"
            "燕无咎也只说会继续往前查，语气和他一样平，像把同一句话递了两遍。\n\n"
            "苏半夏没有再争，只说大家都继续往前查。"
        )
        cards = [
            CharacterVoiceCard(
                name="顾平生",
                speech_rhythm="短句压着说",
                emotional_expression="少外露",
                sentence_shape="硬切",
                contrast_anchor="先认账，再认人",
                common_words=["认账", "照规矩"],
            ),
            CharacterVoiceCard(
                name="燕无咎",
                speech_rhythm="刀口快句",
                emotional_expression="急躁外露",
                sentence_shape="短促",
                contrast_anchor="先动手，再开口",
                common_words=["动手", "别磨"],
            ),
        ]
        report = analyze_chapter(
            text,
            140,
            ["顾平生", "燕无咎", "苏半夏"],
            voice_cards=cards,
            ending_window=True,
        )
        self.assertTrue(any("声口差异不够明显" in issue for issue in report.issues))

    def test_quality_hard_fails_for_severe_procedural_density(self) -> None:
        text = (
            "顾平生把总赔单、回补单、停单表、核算口径、留档凭证、递送链回执和报备票据一并摊开，"
            "先对编号，再对字段，再对账页，再对口供，再对票据，再对条款，逼着所有人按同一套流程认账。\n\n"
            "他又把名单索引、赔付说明、停单记录、争议字段、核算编号和回执抄到台账边上，"
            "继续让账房按流程核验字段、条款、口径、票据、编号和回补说明。"
        )
        report = analyze_chapter(
            text,
            260,
            ["顾平生"],
            term_budget="low",
        )
        self.assertFalse(report.passed)
        self.assertTrue(report.metrics["procedural_density_hard_fail"])

    def test_quality_hard_fails_for_ending_voice_convergence_without_anchors(self) -> None:
        text = (
            "顾平生说继续往前查。\n\n"
            "燕无咎也说继续往前查。\n\n"
            "苏半夏还是说继续往前查。"
        )
        cards = [
            CharacterVoiceCard(
                name="顾平生",
                speech_rhythm="短句压着说",
                emotional_expression="少外露",
                sentence_shape="硬切",
                social_register="先认规矩再认人",
                humor_style="几乎不开玩笑",
                silence_pattern="先停一下",
                contrast_anchor="先认账，再认人",
                common_words=["认账", "照规矩"],
            ),
            CharacterVoiceCard(
                name="燕无咎",
                speech_rhythm="刀口快句",
                emotional_expression="急躁外露",
                sentence_shape="短促",
                social_register="不耐烦，先压火再开口",
                humor_style="冷硬挤兑",
                silence_pattern="几乎不停",
                contrast_anchor="先动手，再开口",
                common_words=["动手", "别磨"],
            ),
        ]
        report = analyze_chapter(
            text,
            80,
            ["顾平生", "燕无咎", "苏半夏"],
            voice_cards=cards,
            ending_window=True,
        )
        self.assertFalse(report.passed)
        self.assertTrue(report.metrics["ending_voice_hard_fail"])


if __name__ == "__main__":
    unittest.main()
