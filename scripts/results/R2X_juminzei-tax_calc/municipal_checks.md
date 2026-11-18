# 自治体のページの文字列の検査

| ファイル | 文字列 | 結果 |
|---|---|---|
| nagoya_keisanrei.txt | 市民税・県民税の計算例（令和8年度） | OK |
| nagoya_keisanrei.txt | 3,963,200円－2,400,600円＝1,562,600円→1,562,000円(1,000円未満切捨) | OK |
| nagoya_keisanrei.txt | 1,562,000円×7.7%＝120,274円 | OK |
| nagoya_keisanrei.txt | 1,562,000円×2%＝31,240円 | OK |
| nagoya_keisanrei.txt | 市民税調整控除額 330,000円×4%＝13,200円 | OK |
| nagoya_keisanrei.txt | 120,274円－13,200円+2,800円＝109,874円→109,800円(100円未満切捨) | OK |
| nagoya_keisanrei.txt | 31,240円－3,300円＋1,500円＝29,440円→29,400円(100円未満切捨) | OK |
| nagoya_keisanrei.txt | 139,200円＋1,000円＝140,200円 | OK |
| nagoya_keisanrei.txt | 名古屋市市民税減税を適用した税率 | OK |
| yokohama_keisan.txt | 2,437,000円×8％（市民税の税率）＝194,960円 | OK |
| yokohama_keisan.txt | 2,437,000円×2.025％（県民税の税率）＝49,349.25円→49,349円（1円未満切捨） | OK |
| yokohama_keisan.txt | 50,000円×4％＝2,000円 | OK |
| yokohama_keisan.txt | 50,000円×1％＝500円 | OK |
| yokohama_keisan.txt | 194,960円－2,000円＝192,960円→192,900円（百円未満切捨） | OK |
| yokohama_keisan.txt | 49,349円－500円＝48,849円→48,800円（百円未満切捨） | OK |
| yokohama_keisan.txt | 3,900円（市民税）＋1,300円（県民税）＝5,200円 | OK |
| yokohama_keisan.txt | 241,700円＋5,200円＋1,000円＝247,900円 | OK |
| chuo_zeigakukoujo.txt | 税額控除は次の順序で控除します。 | OK |
| chuo_zeigakukoujo.txt | 1円未満の端数がある場合は、1円に切り上げ | OK |
| chuo_zeigakukoujo.txt | 配偶者特別控除（配偶者の合計所得金額が48万円超50万円未満） | OK |
| soumu_choka.txt | 超過課税実施団体数（令和7年4月1日現在） | OK |
| soumu_choka.txt | ＜道府県民税＞個人均等割 37団体 | OK |
| soumu_choka.txt | 所得割 1団体 神奈川県 | OK |
| soumu_choka.txt | ＜市町村民税＞個人均等割 2団体 神奈川県横浜市、兵庫県神戸市 | OK |
| soumu_choka.txt | 所得割 1団体 兵庫県豊岡市 | OK |
