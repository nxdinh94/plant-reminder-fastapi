from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeArticle, KnowledgeTopic


@dataclass(frozen=True)
class ArticleSeed:
    slug: str
    title: str
    summary: str
    read_minutes: int
    why_it_matters: str
    steps: tuple[str, ...]
    mistakes: tuple[str, ...]
    troubleshooting: tuple[str, ...]


@dataclass(frozen=True)
class TopicSeed:
    slug: str
    title: str
    description: str
    cover_image_url: str
    articles: tuple[ArticleSeed, ...]


TOPICS: tuple[TopicSeed, ...] = (
    TopicSeed(
        slug="smart-watering",
        title="Tưới nước thông minh",
        description="Xây dựng thói quen tưới nước nhất quán bằng cách kiểm tra độ ẩm, điều kiện thời tiết và dấu hiệu của cây.",
        cover_image_url="https://images.unsplash.com/photo-1485955900006-10f4d324d411?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "watering-check-soil-correctly",
                "Cách kiểm tra độ ẩm của đất đúng cách",
                "Kiểm tra độ sâu của ngón tay, dùng que xiên gỗ và kiểm tra trọng lượng chậu trước mỗi lần tưới.",
                6,
                "Hầu hết các lỗi tưới nước xảy ra khi mọi người làm theo lịch cố định thay vì kiểm tra độ ẩm thực tế của vùng rễ.",
                (
                    "Đâm ngón tay sâu khoảng 2-5 cm vào đất tùy thuộc vào kích thước chậu.",
                    "Sử dụng que xiên gỗ cắm sâu gần bầu rễ để kiểm tra các lớp đất sâu hơn.",
                    "Nhấc chậu sau khi tưới và trước lần tưới tiếp theo để cảm nhận sự khác biệt về trọng lượng.",
                    "Chỉ tưới nước khi mức độ khô của đất phù hợp với khả năng chịu đựng của loại cây đó.",
                ),
                (
                    "Chỉ kiểm tra lớp đất bề mặt sâu khoảng 1 cm.",
                    "Tưới nước chỉ vì lá cây trông hơi rũ xuống dưới cái nắng giữa trưa.",
                    "Nghĩ rằng tất cả các cây trên cùng một kệ đều cần tưới nước vào cùng một ngày.",
                ),
                (
                    "Nếu bề mặt đất khô nhưng que xiên vẫn ẩm, hãy đợi thêm 1-2 ngày.",
                    "Nếu chậu vẫn nặng sau hơn 7 ngày, hãy tăng độ thông thoáng và kiểm tra sức khỏe của rễ.",
                ),
            ),
            ArticleSeed(
                "overwatering-recovery-plan",
                "Kế hoạch phục hồi cây trồng trong nhà bị tưới quá nhiều nước",
                "Nhận biết sớm tình trạng thối rễ và phục hồi cây bằng cách cải thiện thoát nước và làm khô đất theo giai đoạn.",
                7,
                "Tưới quá nhiều nước làm giảm lượng oxy xung quanh rễ, nhanh chóng dẫn đến suy yếu rễ và vàng lá.",
                (
                    "Ngừng tưới nước ngay lập tức và di chuyển cây đến nơi có ánh sáng gián tiếp sáng.",
                    "Kiểm tra các lỗ thoát nước và đổ hết nước đọng trong đĩa lót chậu.",
                    "Cắt tỉa các lá vàng, héo úa để giảm tải áp lực cho cây.",
                    "Nếu có mùi chua hoặc rễ chuyển sang màu đen, hãy nhấc cây ra khỏi chậu, cắt bỏ phần rễ thối và trồng lại bằng đất tơi xốp.",
                ),
                (
                    "Bón thêm phân cho cây đang bị yếu hoặc úng nước.",
                    "Để cây ở nơi thiếu ánh sáng khiến đất khô quá chậm.",
                    "Thay sang chậu lớn hơn nhiều ngay sau khi rễ bị tổn thương.",
                ),
                (
                    "Nếu lá tiếp tục vàng sau 10 ngày, hãy kiểm tra lại xem rễ còn bị thối ẩn hay không.",
                    "Nếu xuất hiện ruồi giấm, hãy để lớp đất mặt khô hoàn toàn và rải một lớp sỏi/cát mỏng lên trên.",
                ),
            ),
            ArticleSeed(
                "underwatering-rehydration",
                "Bù nước an toàn cho đất bị khô cằn nghiêm trọng",
                "Khắc phục hỗn hợp đất bị khô cứng không thấm nước bằng cách ngâm đất theo giai đoạn, tránh dội nước ồ ạt một lần.",
                6,
                "Đất trồng quá khô sẽ đẩy nước (kỵ nước); tưới một lần nhanh thường chỉ làm nước chảy tuột xuống khe chậu mà không thấm vào rễ.",
                (
                    "Tưới nước từ từ thành 2-3 đợt, mỗi đợt cách nhau từ 5-10 phút.",
                    "Sử dụng phương pháp tưới thấm ngược từ dưới lên trong 20-30 phút đối với bầu rễ bị bó chặt.",
                    "Dùng tăm hoặc đũa xới nhẹ lớp đất mặt để nước dễ thấm sâu vào bên dưới.",
                    "Chỉ quay lại lịch tưới bình thường sau khi độ ẩm đã được phân bổ đều khắp chậu.",
                ),
                (
                    "Chỉ dội nước một lần và mặc định rễ đã hút đủ nước.",
                    "Ngâm chậu dưới nước hàng giờ liền gây ngạt và căng thẳng cho rễ.",
                ),
                (
                    "Nếu lá vẫn rũ sau 24 giờ, hãy kiểm tra xem rễ có bị tổn thương hay không chứ không chỉ do đất khô.",
                    "Nếu nước vẫn chảy tuột xuống hai bên thành chậu, hãy thay đất mới tơi xốp và tưới ẩm đúng cách.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="light-placement",
        title="Ánh sáng và Vị trí đặt cây",
        description="Chọn vị trí phù hợp với nhu cầu ánh sáng thực tế của từng loài cây và chuyển động của mặt trời theo mùa.",
        cover_image_url="https://images.unsplash.com/photo-1463320898484-cdee8141c787?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "measure-light-at-home",
                "Cách đo ánh sáng trong nhà đúng cách",
                "Kết hợp hướng cửa sổ, bài kiểm tra bóng râm và ứng dụng đo độ Lux để chọn vị trí phù hợp.",
                6,
                "Đặt cây ở vị trí đủ sáng giúp hạn chế tình trạng chậm lớn, rụng lá và ngăn ngừa sâu bệnh tấn công.",
                (
                    "Xác định hướng của cửa sổ: đông, tây, nam hoặc bắc.",
                    "Sử dụng ứng dụng đo độ Lux trên điện thoại tại vị trí lá cây vào lúc 9 giờ sáng, 12 giờ trưa và 3 giờ chiều.",
                    "Phân loại các khu vực: ánh sáng yếu, trung bình, sáng gián tiếp hoặc ánh nắng trực tiếp.",
                    "Xếp từng nhóm cây vào khu vực phù hợp và dán nhãn các kệ cây để duy trì sự nhất quán.",
                ),
                (
                    "Chỉ đo cường độ ánh sáng một lần duy nhất trong ngày.",
                    "Bỏ qua sự thay đổi góc chiếu của mặt trời theo từng mùa.",
                    "Đặt cây quá sát mặt kính nóng vào buổi chiều.",
                ),
                (
                    "Nếu lá bị bạc màu sau khi chuyển vị trí, hãy dời chậu cây ra xa cửa sổ khoảng 30-60 cm.",
                    "Nếu các đốt thân dài ra bất thường, hãy tăng thời gian chiếu sáng hoặc chuyển cây đến khu vực sáng hơn.",
                ),
            ),
            ArticleSeed(
                "grow-light-setup-guide",
                "Hướng quan sát lắp đèn quang hợp cho căn hộ",
                "Thiết lập khoảng cách, thời gian chiếu sáng và độ cao treo đèn phù hợp để cây phát triển ổn định.",
                7,
                "Đèn quang hợp có thể thay thế hoàn toàn ánh sáng tự nhiên từ cửa sổ nếu được điều chỉnh cường độ và thời gian hợp lý.",
                (
                    "Bắt đầu với thanh đèn LED quang hợp toàn phổ đặt cách ngọn cây khoảng 20-40 cm.",
                    "Bật đèn từ 10-12 giờ đối với cây cảnh lá và 12-14 giờ đối với rau gia vị và cây con.",
                    "Sử dụng ổ cắm hẹn giờ để duy trì khung giờ chiếu sáng cố định hàng ngày.",
                    "Nâng cao đèn hoặc giảm độ sáng khi đầu lá bị nhạt màu hoặc xoăn ngược lên.",
                ),
                (
                    "Bật đèn liên tục 24 giờ mà không cho cây có thời gian nghỉ trong bóng tối.",
                    "Đặt đèn quá xa khiến thân cây bị vươn dài và yếu ớt.",
                ),
                (
                    "Nếu rêu tảo hình thành trên mặt đất, hãy giảm tưới nước và tăng cường độ thông thoáng.",
                    "Nếu lá nhỏ và nhạt màu, hãy tăng dần cường độ ánh sáng trong vòng một tuần.",
                ),
            ),
            ArticleSeed(
                "window-placement-mistakes",
                "Những sai lầm phổ biến khi đặt cây gần cửa sổ",
                "Tránh luồng gió nóng từ điều hòa, sốc nhiệt từ kính lạnh và các góc tối bị che khuất.",
                5,
                "Một giống cây tốt vẫn có thể lụi tàn nếu vi khí hậu quanh cửa sổ không ổn định.",
                (
                    "Để các cây nhiệt đới tránh xa luồng gió trực tiếp từ máy điều hòa hoặc máy sưởi.",
                    "Xoay chậu cây 1-2 tuần một lần để tán lá phát triển đều các hướng.",
                    "Sử dụng rèm mỏng để che bớt ánh nắng gay gắt phía tây vào buổi chiều.",
                ),
                (
                    "Đặt cây phía sau rèm cản sáng dày.",
                    "Bỏ qua sự sụt giảm nhiệt độ ban đêm sát cửa sổ vào mùa lạnh.",
                ),
                (
                    "Nếu cây bị nghiêng hẳn về một phía, hãy xoay chậu và cắt tỉa nhẹ để cân bằng tán.",
                    "Nếu xuất hiện tổn thương do lạnh, hãy dời chậu cây ra xa mặt kính khoảng 20-30 cm vào ban đêm.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="soil-root-health",
        title="Đất trồng và Sức khỏe rễ",
        description="Tự trộn đất tơi xốp, thoáng khí và thay chậu đúng kỹ thuật để bộ rễ phát triển khỏe mạnh.",
        cover_image_url="https://images.unsplash.com/photo-1472396961693-142e6e269027?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "potting-mix-components-explained",
                "Giải thích các thành phần trong đất trộn",
                "Hiểu rõ xơ dừa, vỏ thông, đá trân châu (perlite), phân compost và đá bọt (pumice) ảnh hưởng thế nào đến độ ẩm và độ thoáng khí.",
                7,
                "Sự cân bằng giữa oxy và độ ẩm ở vùng rễ quyết định việc cây sẽ phát triển tươi tốt hay lụi tàn dần.",
                (
                    "Sử dụng xơ dừa hoặc rêu than bùn làm lớp nền giữ ẩm.",
                    "Thêm vỏ thông và đá bọt/đá trân châu để tạo các khoảng trống chứa khí.",
                    "Đối với các loại cây kiểng lá nhiệt đới (aroid), hãy hướng tới hỗn hợp đất thô, thoát nước cực nhanh.",
                    "Đối với rau và thảo mộc trồng trong chậu, hãy trộn thêm phân compost để bổ dung dinh dưỡng.",
                ),
                (
                    "Sử dụng đất vườn thông thường cho chậu trồng trong nhà.",
                    "Nén đất quá chặt làm rễ bị ngạt khí.",
                ),
                (
                    "If đất ẩm quá lâu, hãy trộn thêm các thành phần đá khoáng để tăng độ thoát khí.",
                    "Nếu đất khô sạch chỉ trong một ngày, hãy tăng tỷ lệ các thành phần giữ ẩm mịn.",
                ),
            ),
            ArticleSeed(
                "repotting-with-minimal-shock",
                "Thay chậu giảm thiểu sốc cho cây",
                "Thực hiện quy trình thay chậu nhẹ nhàng để bảo vệ bộ rễ đang phát triển và rút ngắn thời gian hồi phục.",
                8,
                "Hiện tượng sốc sau khi thay chậu thường do rễ bị tác động mạnh, chọn sai thời điểm hoặc thay đổi môi trường quá đột ngột.",
                (
                    "Thay chậu vào mùa sinh trưởng khi cây có khả năng phục hồi nhanh nhất.",
                    "Chọn chậu mới chỉ lớn hơn chậu cũ khoảng 2-4 cm về đường kính.",
                    "Nhẹ nhàng gỡ các rễ bị bó tròn; chỉ cắt tỉa phần rễ đã chết hoặc thối nhũn.",
                    "Sau khi thay chậu, tưới nước thật đẫm một lần, sau đó theo dõi sát độ ẩm đất trong một tuần.",
                ),
                (
                    "Chuyển cây sang chậu quá cỡ khiến đất giữ quá nhiều nước dư thừa.",
                    "Bón phân ngay lập tức sau khi bộ rễ vừa bị tác động.",
                ),
                (
                    "Nếu lá bị rũ trong 2-3 ngày đầu, hãy để cây ở nơi ánh sáng gián tiếp và tránh tưới thêm nước.",
                    "Nếu tình trạng yếu đi kéo dài hơn một tuần, hãy kiểm tra tổn thương rễ hoặc khả năng thoát nước.",
                ),
            ),
            ArticleSeed(
                "salt-buildup-soil-reset",
                "Cách xử lý đất trồng bị tích tụ muối",
                "Rửa trôi lượng muối dư thừa từ phân bón và làm mới đất bị nén chặt trước khi rễ bị cháy.",
                5,
                "Tích tụ muối quá nhiều có thể gây ra các triệu chứng giống như thiếu dinh dưỡng nhưng thực chất lại làm cháy đầu rễ.",
                (
                    "Xả nước sạch vào chậu liên tục với lượng nước gấp 2-3 lần thể tích chậu.",
                    "Để chậu thoát nước hoàn toàn và lặp lại sau 24 giờ nếu lớp màng trắng vẫn còn.",
                    "Cắt tỉa những lá bị hư hỏng nặng và bón phân trở lại với liều lượng giảm một nửa.",
                ),
                (
                    "Sử dụng phân bón đậm đặc để khắc phục tình trạng cháy lá do tích tụ muối.",
                    "Bỏ qua việc kiểm tra thoát nước trong quá trình xả đất.",
                ),
                (
                    "Nếu lớp màng muối trắng xuất hiện lại nhanh chóng, hãy giảm nồng độ và tần suất bón phân.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="pests-disease-control",
        title="Kiểm soát Sâu bệnh",
        description="Phát hiện sớm, cách ly và thực hiện các chu kỳ điều trị triệt để cho các loại sâu bệnh trong nhà phổ biến.",
        cover_image_url="https://images.unsplash.com/photo-1524593119779-9d82b2ca2b18?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "weekly-pest-inspection-routine",
                "Thói quen kiểm tra sâu bệnh hàng tuần",
                "Phát hiện nhện đỏ, bọ trĩ, rệp vảy và rệp sáp trước khi chúng lây lan ra khắp kệ cây.",
                5,
                "Sâu bệnh dễ kiểm soát nhất ở giai đoạn đầu khi số lượng còn ít và khu trú ở diện hẹp.",
                (
                    "Dùng đèn pin kiểm tra kỹ mặt dưới lá, các nách lá và chồi non.",
                    "Quan sát các vệt dính, các đốm nhỏ đổi màu hoặc các vết xước màu bạc trên lá.",
                    "Cách ly ngay lập tức những cây nghi ngờ bị nhiễm bệnh sang khu vực riêng.",
                ),
                (
                    "Phun thuốc bừa bãi cho toàn bộ vườn khi chưa xác định đúng loại bệnh.",
                    "Bỏ qua việc kiểm tra theo dõi sau đợt phun thuốc đầu tiên.",
                ),
                (
                    "Nếu nhiều cây bị nhiễm bệnh, hãy lập bản đồ khu vực lây nhiễm và xử lý theo từng đợt.",
                ),
            ),
            ArticleSeed(
                "spider-mite-treatment-plan",
                "Kế hoạch điều trị nhện đỏ tận gốc",
                "Vòi xịt rửa sạch, phun thuốc đặc trị và lặp lại đúng chu kỳ để cắt đứt vòng đời của nhện đỏ.",
                7,
                "Nhện đỏ sinh sản cực nhanh trong điều kiện khô ấm và gây suy kiệt lá liên tục.",
                (
                    "Rửa sạch toàn bộ tán lá bằng vòi xịt nước, đặc biệt chú ý mặt dưới lá.",
                    "Phun xịt xà phòng diệt côn trùng hoặc dầu khoáng sinh học theo hướng dẫn.",
                    "Lặp lại việc phun xịt sau mỗi 4-7 ngày trong ít nhất 3 chu kỳ liên tiếp.",
                    "Tăng cường độ ẩm và giữ lưu thông gió để giảm thiểu nguy cơ tái nhiễm.",
                ),
                (
                    "Chỉ phun xịt một lần rồi dừng lại quá sớm.",
                    "Phun thuốc dưới ánh nắng trực tiếp gây cháy lá.",
                ),
                (
                    "Nếu các vệt đốm mới tiếp tục xuất hiện sau chu kỳ 2, hãy kéo dài điều trị thêm hai đợt nữa.",
                ),
            ),
            ArticleSeed(
                "fungus-gnat-control",
                "Kiểm soát ruồi giấm/muỗi nấm không dùng hóa chất",
                "Kết hợp kiểm soát tưới nước, bẫy dính và các biện pháp sinh học để diệt tận gốc muỗi nấm.",
                6,
                "Muỗi nấm phát triển mạnh trong đất hữu cơ ẩm ướt liên tục và ấu trùng của chúng có thể cắn phá rễ non.",
                (
                    "Để 2-3 cm lớp đất mặt khô hoàn toàn giữa các lần tưới.",
                    "Sử dụng bẫy dính màu vàng để thu hút và theo dõi lượng ruồi trưởng thành.",
                    "Phủ một lớp cát hoặc đá cuội nhỏ lên mặt chậu để ngăn ruồi đẻ trứng.",
                    "Sử dụng chế phẩm sinh học chứa vi khuẩn BTI hoặc tuyến trùng có lợi nếu bị nhiễm nặng.",
                ),
                (
                    "Giữ đất ẩm liên tục cho mọi loại cây trong nhà.",
                    "Chỉ tiêu diệt ruồi bay mà bỏ qua giai đoạn ấu trùng trong đất.",
                ),
                (
                    "Nếu số lượng ruồi không giảm sau 10 ngày, hãy kiểm tra xem có khay đọng nước nào dưới đáy chậu hay không.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="propagation-multiplication",
        title="Nhân giống cây trồng",
        description="Nhân giống cây khỏe mạnh bằng phương pháp giâm cành, tách bụi và kiểm soát độ ẩm.",
        cover_image_url="https://images.unsplash.com/photo-1512428559087-560fa5ceab42?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "stem-cutting-basics",
                "Kiến thức cơ bản về giâm cành",
                "Lựa chọn các đoạn cành có mắt ngủ khỏe mạnh và kích rễ trong môi trường đủ ẩm và ánh sáng ổn định.",
                6,
                "Chất lượng cành giâm và việc vệ sinh dụng cụ quyết định tốc độ ra rễ và tỷ lệ thành công.",
                (
                    "Khử trùng kéo/dao cắt trước khi tiến hành trên mỗi cây.",
                    "Cắt dưới mắt ngủ khoảng 1-2 cm từ một cành khỏe mạnh có ít nhất một lá.",
                    "Loại bỏ các lá ở phần gốc cành để tránh bị ngập trong nước hoặc giá thể.",
                    "Đặt cành giâm ở nơi có ánh sáng gián tiếp ấm và nhiệt độ ổn định.",
                ),
                (
                    "Sử dụng các đoạn thân yếu, còi cọc vươn dài để nhân giống.",
                    "Để cành giâm bị khô quá lâu trước khi cho vào môi trường kích rễ.",
                ),
                (
                    "Nếu phần gốc cành giâm bị thối nhũn, hãy cắt bỏ phần hư hại và thực hiện lại.",
                ),
            ),
            ArticleSeed(
                "water-vs-soil-propagation",
                "Nhân giống trong nước so với trong đất",
                "Lựa chọn môi trường nhân giống dựa trên đặc tính của cây, nguy cơ thối rễ và khả năng thích nghi.",
                6,
                "Mỗi loài cây phản ứng khác nhau; chọn đúng môi trường giúp nâng cao tỷ lệ sống của cây con.",
                (
                    "Sử dụng phương pháp giâm nước để dễ dàng quan sát rễ phát triển đối với các loài dễ trồng.",
                    "Giâm trực tiếp trong giá thể tơi xốp để tránh hiện tượng sốc khi chuyển từ nước sang đất.",
                    "Thay nước sạch định kỳ 3-5 ngày một lần nếu giâm trong nước.",
                ),
                (
                    "Để cành giâm trong nước cũ tù đọng lâu ngày.",
                    "Chuyển cành giâm vừa ra rễ từ nước vào loại đất quá nén chặt.",
                ),
                (
                    "Nếu rễ chậm phát triển, hãy tăng độ ấm và kiểm tra lại cường độ ánh sáng.",
                ),
            ),
            ArticleSeed(
                "transfer-rooted-cuttings",
                "Chuyển cành giâm đã ra rễ vào đất",
                "Chuyển cành giâm vào giá thể ẩm nhẹ và điều chỉnh độ ẩm môi trường từ từ.",
                7,
                "Hầu hết các trường hợp thất bại xảy ra trong quá trình chuyển chậu chứ không phải lúc kích rễ.",
                (
                    "Chuyển cành giâm khi rễ dài khoảng 3-5 cm và bắt đầu phân nhánh.",
                    "Sử dụng chậu nhỏ với hỗn hợp đất tơi xốp đã được làm ẩm trước.",
                    "Giữ đất ẩm đều trong 7-10 ngày đầu trước khi giảm dần về lịch tưới thông thường.",
                ),
                (
                    "Đợi đến khi rễ quá dài và giòn mới đem trồng đất.",
                    "Để đất trồng mới bị khô hạn hoàn toàn trong tuần đầu tiên.",
                ),
                (
                    "Nếu lá tiếp tục héo sau 48 giờ, hãy tạm thời chụp túi nilon để giữ ẩm.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="seasonal-climate-care",
        title="Chăm sóc theo mùa và khí hậu",
        description="Điều chỉnh chế độ chăm sóc cho mùa nắng nóng, mùa mưa và mùa lạnh với các danh mục kiểm tra thực tế.",
        cover_image_url="https://images.unsplash.com/photo-1471193945509-9ad0617afabf?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "summer-heat-protection",
                "Bảo vệ cây trồng trong chậu khỏi nắng nóng mùa hè",
                "Bảo vệ tán lá và bộ rễ trong các đợt nắng nóng bằng cách che mát và tưới nước thông minh.",
                6,
                "Cây trồng trong chậu bị nóng và khô nhanh hơn nhiều so với cây trồng trực tiếp xuống đất vườn.",
                (
                    "Di chuyển những cây nhạy cảm ra khỏi khu vực hứng nắng chiều trực tiếp.",
                    "Tưới nước thật đẫm vào sáng sớm thay vì tưới lướt qua nhiều lần.",
                    "Phủ một lớp giá thể thô lên mặt chậu để hạn chế bốc hơi nước.",
                    "Xếp các chậu cây lại gần nhau để tạo vùng vi khí hậu mát mẻ hơn.",
                ),
                (
                    "Tưới nước vào giữa trưa nắng nóng làm rễ bị sốc nhiệt.",
                    "Sử dụng chậu nhựa đen ở những vị trí hướng tây mà không có che chắn.",
                ),
                (
                    "If lá bị cháy nắng đột ngột, hãy che lưới mát tạm thời trong 3-5 ngày.",
                ),
            ),
            ArticleSeed(
                "rainy-season-root-protection",
                "Bảo vệ rễ cây trong mùa mưa",
                "Ngăn ngừa thối rễ và rửa trôi chất dinh dưỡng khi thời tiết mưa dầm kéo dài.",
                5,
                "Mưa dầm làm đất sũng nước gây thiếu oxy và dễ phát sinh nấm hại rễ trong chậu.",
                (
                    "Kê cao chậu để đảm bảo lỗ thoát nước dưới đáy không bị tắc nghẽn.",
                    "Giảm tần suất tưới và kiểm tra độ ẩm sâu dưới bầu đất.",
                    "Tạo khoảng cách giữa các cây để tăng độ thông thoáng.",
                ),
                (
                    "Vẫn giữ lịch tưới của mùa khô khi trời mưa liên tục.",
                    "Để khay lót chậu đầy nước sau các cơn mưa lớn.",
                ),
                (
                    "Nếu các lá phía dưới bị vàng nhanh chóng, hãy kiểm tra rễ và cân nhắc thay một phần đất mới.",
                ),
            ),
            ArticleSeed(
                "vacation-care-plan",
                "Kế hoạch tự chăm sóc cây khi đi du lịch (3-14 ngày)",
                "Thiết lập hệ thống tưới nước tự động và ánh sáng phù hợp trước khi bạn đi xa.",
                5,
                "Hầu hết các sự cố chết cây khi chủ đi vắng là do khâu chuẩn bị chưa tốt chứ không hẳn do số ngày đi lâu.",
                (
                    "Tưới nước thật đẫm cho cây khoảng 24 giờ trước khi khởi hành.",
                    "Dời cây ra khỏi các khu vực nắng gắt để giảm nhu cầu thoát nước.",
                    "Sử dụng dây hút nước (bấc) hoặc các bình tự tưới cho những loài ưa ẩm.",
                    "Gom các chậu cây lại gần nhau và đặt trên khay đá cuội chứa nước để duy trì độ ẩm xung quanh.",
                ),
                (
                    "Bón phân ngay trước khi đi du lịch.",
                    "Để cây ở vị trí nhận quá nhiều nắng mà không có sự điều chỉnh nào.",
                ),
                (
                    "Khi trở về gặp cây bị héo khô, hãy bù nước từ từ trong vòng 24 giờ thay vì dội nước ngập chậu ngay.",
                ),
            ),
        ),
    ),
    TopicSeed(
        slug="edible-gardening",
        title="Trồng rau gia vị và cây ăn quả",
        description="Trồng thảo mộc và rau củ nhỏ gọn tại ban công, sân thượng và các khu vườn nhỏ tại nhà.",
        cover_image_url="https://images.unsplash.com/photo-1466692476868-aef1dfb1e735?auto=format&fit=crop&w=1200&q=80",
        articles=(
            ArticleSeed(
                "kitchen-herbs-beginner-plan",
                "Kế hoạch trồng rau gia vị cho người mới bắt đầu",
                "Trồng húng quế, bạc hà và ngò tây với kỹ thuật giãn cách chậu, cắt tỉa và thu hoạch đúng lúc.",
                6,
                "Rau gia vị lớn nhanh và cho thu hoạch hàng ngày, rất lý tưởng để thực hành làm vườn thường xuyên.",
                (
                    "Sử dụng chậu đường kính 15-20 cm với hỗn hợp đất thoát nước tốt.",
                    "Đảm bảo húng quế và bạc hà nhận được ít nhất 4-6 giờ nắng mạnh.",
                    "Bấm ngọn định kỳ hàng tuần để kích thích cây phân nhánh nhiều.",
                ),
                (
                    "Thu hoạch quá nhiều khi cây còn quá nhỏ.",
                    "Trồng chung bạc hà với các loại rau khác trong cùng một chậu (bạc hà sẽ lấn át).",
                ),
                (
                    "Nếu húng quế ra hoa sớm, hãy ngắt bỏ ngọn hoa và điều chỉnh lại lượng ánh sáng và dinh dưỡng.",
                ),
            ),
            ArticleSeed(
                "chili-pepper-in-pots",
                "Hướng dẫn thực tế trồng ớt trong chậu",
                "Quản lý ánh sáng, bón phân và các giai đoạn ra hoa kết trái cho cây ớt trồng trong chậu.",
                7,
                "Cây lấy quả có nhu cầu về nước và dinh dưỡng rất khác so với cây cảnh chơi lá.",
                (
                    "Bắt đầu với chậu sâu ít nhất 25-30 cm và đặt ở vị trí có nắng mạnh.",
                    "Bón phân cân đối ở giai đoạn phát triển thân lá, sau đó tăng kali khi cây ra hoa.",
                    "Làm cọc đỡ nhánh khi quả bắt đầu ra nhiều để tránh gãy cành.",
                ),
                (
                    "Tưới quá nhiều nước trong những giai đoạn thời tiết mát mẻ.",
                    "Bón phân nhiều đạm ở giai đoạn muộn làm cây chỉ tốt lá mà không ra quả.",
                ),
                (
                    "Nếu hoa bị rụng, hãy kiểm tra sốc nhiệt, tưới nước thất thường hoặc thiếu thụ phấn.",
                ),
            ),
            ArticleSeed(
                "leafy-greens-quick-cycle",
                "Trồng rau ăn lá ngắn ngày tại nhà",
                "Trồng xà lách và các loại rau cải ngắn ngày bằng cách gieo hạt liên tiếp gối vụ.",
                5,
                "Các loại rau lớn nhanh giúp tạo động lực và mang lại nguồn thu hoạch đều đặn ngay cả trong không gian hẹp.",
                (
                    "Gieo các đợt hạt nhỏ cách nhau 7-10 ngày để có rau thu hoạch liên tục.",
                    "Giữ đất ẩm độ ẩm đều nhưng không được để sũng nước.",
                    "Thu hoạch các lá già bên ngoài trước để cây tiếp tục phát triển lá non.",
                ),
                (
                    "Gieo tất cả hạt cùng một lúc dẫn đến thừa rau một đợt rồi đứt lứa.",
                    "Không chú ý che chắn nắng nóng khiến rau dễ bị đắng và ra hoa sớm.",
                ),
                (
                    "Nếu rau bị đắng, hãy chuyển chậu vào vị trí mát hơn và thu hoạch khi lá còn non.",
                ),
            ),
        ),
    ),
)


def _build_html(topic_title: str, article: ArticleSeed) -> str:
    safe_summary = article.summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_why = article.why_it_matters.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    steps_html = "".join(f"<li>{step}</li>" for step in article.steps)
    mistakes_html = "".join(f"<li>{mistake}</li>" for mistake in article.mistakes)
    troubleshooting_html = "".join(f"<li>{tip}</li>" for tip in article.troubleshooting)

    return (
        f"<h2>{article.title}</h2>"
        f"<p>{safe_summary}</p>"
        "<h3>Why it matters</h3>"
        f"<p>{safe_why}</p>"
        f"<p>This guide belongs to <strong>{topic_title}</strong> and is designed for real home-growing conditions.</p>"
        "<h3>Step-by-step</h3>"
        f"<ol>{steps_html}</ol>"
        "<h3>Common mistakes</h3>"
        f"<ul>{mistakes_html}</ul>"
        "<h3>Troubleshooting</h3>"
        f"<ul>{troubleshooting_html}</ul>"
    )


def seed_knowledge_content() -> tuple[int, int]:
    db = SessionLocal()
    topic_count = 0
    article_count = 0
    try:
        for topic_index, topic_seed in enumerate(TOPICS):
            topic = db.execute(
                select(KnowledgeTopic).where(KnowledgeTopic.slug == topic_seed.slug)
            ).scalar_one_or_none()

            if topic is None:
                topic = KnowledgeTopic(slug=topic_seed.slug)
                db.add(topic)

            topic.title = topic_seed.title
            topic.description = topic_seed.description
            topic.cover_image_url = topic_seed.cover_image_url
            topic.sort_order = topic_index
            topic_count += 1

            db.flush()

            for article_index, article_seed in enumerate(topic_seed.articles):
                article = db.execute(
                    select(KnowledgeArticle).where(KnowledgeArticle.slug == article_seed.slug)
                ).scalar_one_or_none()

                if article is None:
                    article = KnowledgeArticle(slug=article_seed.slug)
                    db.add(article)

                article.topic_id = topic.id
                article.title = article_seed.title
                article.summary = article_seed.summary
                article.hero_image_url = topic_seed.cover_image_url
                article.html_content = _build_html(topic_seed.title, article_seed)
                article.read_minutes = article_seed.read_minutes
                article.sort_order = article_index
                article_count += 1

        db.commit()
        return topic_count, article_count
    finally:
        db.close()


if __name__ == "__main__":
    topics, articles = seed_knowledge_content()
    print(f"Seeded knowledge content: topics={topics}, articles={articles}")
